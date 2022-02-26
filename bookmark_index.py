#!/usr/bin/python
# encoding: utf-8

import codecs
import json
import sqlite3
import os
from os.path import expanduser, isfile
import shutil

from whoosh import index, qparser, query, fields, analysis
from whoosh.analysis import CharsetFilter, StemmingAnalyzer
from whoosh.fields import STORED, NUMERIC, TEXT
from whoosh.support.charset import accent_map

BACKGROUND_JOB_KEY = "updateIndex"
UPDATE_INDEX_COMMAND = "update_index.py"
INDEX_PREFIX = "bookmarks-"
INDEXING_SETTING = "indexing"
CURRENT_INDEX_SETTING = "currentIndex"
INDEX_FRESH_CACHE = "freshIndex"
_N_GRAM_FIELD = "content"
_TEXT_FIELD = "title"
_CHILDREN_KEY = "children"

_BLUE_INDEX = "blue"
_GREEN_INDEX = "green"

_TEXT_ANALYZER = StemmingAnalyzer() | CharsetFilter(accent_map)
_N_GRAM_ANALYZER = analysis.NgramWordAnalyzer(minsize=2, maxsize=10, at='start')

IGNORE_ROOT_BOOKMARKS = ("Bookmarks Bar", "Other Bookmarks", "Mobile Bookmarks")

DB_HISTORY = {}
SQL_QUERY_old = "SELECT visit_count FROM urls WHERE url=?;"
SQL_QUERY = """
    SELECT count(*)
    FROM visits
    JOIN urls
    WHERE urls.id=visits.url
    AND urls.url=?
    AND visits.visit_duration >0;
    """

class BookmarkSchema(fields.SchemaClass):
    title = TEXT(stored=True, analyzer=_TEXT_ANALYZER, phrase=True)
    content = TEXT(stored=False, analyzer=_N_GRAM_ANALYZER, phrase=False)
    freq = NUMERIC(stored=True, signed=False, sortable=True, default=0)
    urlSize = NUMERIC(stored=True, signed=False, sortable=False, default=0)
    path = STORED()
    profile = STORED()
    url = STORED()
    icon = STORED()


class BookmarkIndex:

    def __init__(self, wf):
        self._wf = wf
        self._cacheDir = wf.cachedir
        self._schema = BookmarkSchema()

    def get_bookmark_tree(self, tree, writer, path, icon_filename, profile):
        if type(tree) is not dict:
            return
        wf = self._wf
        cur = DB_HISTORY[profile].cursor()
        urls = []
        names = [tree['name']]
        freq = 0
        for item in tree[_CHILDREN_KEY]:
            name = item['name']
            item_path = path if path != "" else name
            if _CHILDREN_KEY in item:
                self.get_bookmark_tree(item, writer, item_path, icon_filename, profile)
            else:
                try:
                    cur.execute(SQL_QUERY, (item['url'], ))
                    result = cur.fetchone()
                    if result:
                        count = tuple(result)[0]
                        freq += count
                except sqlite3.OperationalError as e:
                    wf.logger.error("Error executing sqlite query: %s" % e)

                urls.append(item['url'])
                names.append(name)

        title = tree['name']
        if urls and title not in IGNORE_ROOT_BOOKMARKS:
            titles = " ".join(names)
            if freq:
                wf.logger.debug("freq: %d for %s" % (freq, title))
            writer.add_document(title=title,
                                content=titles,
                                freq=int(round(freq/len(urls))),
                                url=" ".join(urls),
                                path=path,
                                profile=profile,
                                icon=icon_filename,
                                urlSize=len(urls))

    def get_bookmarks(self, profiles, writer):
        wf = self._wf
        for profile in profiles:
            profile_dir = expanduser("~/Library/Application Support/Google/Chrome/%s" % profile)
            icon_file = profile_dir + "/Google Profile Picture.png"
            if not isfile(icon_file):
                icon_file = "icon.png"

            bookmark_filename = profile_dir + "/Bookmarks"
            if isfile(bookmark_filename):
                wf.logger.debug("Searching file: %s", bookmark_filename)
                bookmark_file = codecs.open(bookmark_filename, encoding='utf-8')
                bookmark_data = json.load(bookmark_file)
                roots = bookmark_data["roots"]

                for key in roots:
                    self.get_bookmark_tree(roots[key], writer, "", icon_file, profile)

    def index_profiles(self, profiles):
        wf = self._wf
        self.open_history(profiles)

        wf.cache_data(INDEXING_SETTING, True)
        current_index_color = wf.settings.setdefault(CURRENT_INDEX_SETTING, _GREEN_INDEX)
        new_index_color = _BLUE_INDEX if current_index_color == _GREEN_INDEX else _GREEN_INDEX
        new_index_name = INDEX_PREFIX + new_index_color

        wf.logger.info("Building the search index: %s, in cache dir: %s", new_index_name, self._cacheDir)
        the_index = index.create_in(self._cacheDir, schema=self._schema, indexname=new_index_name)
        writer = the_index.writer(limitmb=512)
        self.get_bookmarks(profiles, writer)
        writer.commit()
        wf.logger.info("Completed building the search index: %s", new_index_name)

        self._wf.settings[CURRENT_INDEX_SETTING] = new_index_color
        self._wf.settings.save()
        wf.cache_data(INDEXING_SETTING, False)
        wf.cache_data(INDEX_FRESH_CACHE, True)
        self.close_history(profiles)

        return the_index

    def open_index(self, index_name):
        wf = self._wf
        wf.logger.debug("Opening the search index %s in cache dir: %s", index_name, self._cacheDir)
        return index.open_dir(self._cacheDir, indexname=index_name)

    def get_index_if_exists(self):
        current_index_number = self._wf.settings.setdefault(CURRENT_INDEX_SETTING, _GREEN_INDEX)
        index_name = INDEX_PREFIX + str(current_index_number)
        index_exists = index.exists_in(self._cacheDir, indexname=index_name)
        if index_exists:
            return self.open_index(index_name)
        else:
            return None

    def n_gram_query(self, query_string):
        # og = qparser.OrGroup.factory(0.8)
        parser = qparser.QueryParser(_N_GRAM_FIELD, self._schema, group=qparser.AndGroup)
        parser.remove_plugin_class(qparser.FieldsPlugin)
        parser.remove_plugin_class(qparser.WildcardPlugin)
        parser.add_plugin(qparser.FuzzyTermPlugin())
        return parser.parse(query_string)

    @staticmethod
    def all_query():
        return query.Every()

    @staticmethod
    def prefix_query(query_string):
        return query.Prefix(_TEXT_FIELD, query_string)
        # if len(query_string) == 1:

    def open_history(self, profiles):
        wf = self._wf
        for profile in profiles:
            profile_dir = expanduser("~/Library/Application Support/Google/Chrome/%s" % profile)
            history_filename = profile_dir + "/History"
            if isfile(history_filename):
                try:
                    wf.logger.debug("Creating temporary copy of sqlite db for profile %s", profile)
                    new_history_filename = "/tmp/History-{}.db".format(profile)
                    shutil.copy(history_filename, new_history_filename)
                    DB_HISTORY[profile] = sqlite3.connect(new_history_filename)
                except Exception as e:
                    wf.logger.error("Error copying/opening sqlite file %s: %s" % (new_history_filename, e))
                    del DB_HISTORY[profile]

    def close_history(self, profiles):
        wf = self._wf
        for profile in profiles:
            if profile in DB_HISTORY:
                wf.logger.debug("Deleting temporary copy of sqlite db for profile %s", profile)
                DB_HISTORY[profile].close()
                del DB_HISTORY[profile]
                new_history_filename = "/tmp/History-{}.db".format(profile)
                # if os.path.exists(new_history_filename):
                #     os.remove(new_history_filename)

