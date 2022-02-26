#!/usr/bin/python
# encoding: utf-8

import argparse
import sys

from bookmark_index import BookmarkIndex, BACKGROUND_JOB_KEY, INDEX_FRESH_CACHE, UPDATE_INDEX_COMMAND
from workflow import Workflow3, ICON_WARNING
from workflow.background import run_in_background, is_running

UPDATE_SETTINGS = {
    'github_slug': 'jasantunes/alfred-chrome-bookmarks',
    'frequency': 1
}

ICON_UPDATE = 'update-available.png'

# Shown in error logs. Users can find help here
HELP_URL = 'https://github.com/{}'.format(UPDATE_SETTINGS['github_slug'])


def main(wf):
    # Update available?
    if wf.update_available:
        wf.add_item(u'A newer version is available',
                    u'↩ to install update',
                    autocomplete='workflow:update',
                    icon=ICON_UPDATE)

    # build argument parser to parse script args and collect their
    # values
    parser = argparse.ArgumentParser()
    parser.add_argument('query', nargs='?', default=None)
    args = parser.parse_args(wf.args)

    ####################################################################
    # Get saved profiles or use Default
    ####################################################################
    bookmark_index = BookmarkIndex(wf)

    ####################################################################
    # Do Search
    ####################################################################
    ix = bookmark_index.get_index_if_exists()
    if not ix:
        if not is_running(BACKGROUND_JOB_KEY):
            run_in_background(BACKGROUND_JOB_KEY,
                              ['/usr/bin/python',
                               wf.workflowfile(UPDATE_INDEX_COMMAND)])

        wf.rerun = 1
        wf.add_item('Indexing Bookmarks', 'Info will display when complete', icon=ICON_WARNING)
        wf.send_feedback()
        return 0

    with ix.searcher() as searcher:
        if searcher.doc_count() == 0:  # we have no data to show, so show a warning and stop
            wf.add_item('No bookmarks found', 'bm-add to add profiles', icon=ICON_WARNING)
            wf.rerun = 1
            wf.send_feedback()
            return 0

        query_string = args.query
        if query_string:

            # parsed_term_query = bookmark_index.n_gram_query(query_string)
            # results = searcher.search(parsed_term_query, limit=20)
            parsed_query = bookmark_index.prefix_query(query_string)
            results = searcher.search(parsed_query, limit=20, sortedby="freq", reverse=True)
            if len(query_string) > 1:
                parsed_term_query = bookmark_index.n_gram_query(query_string)
                n_gram_results = searcher.search(parsed_term_query, limit=20)
                results.upgrade_and_extend(n_gram_results)
        else:
            results = searcher.search(bookmark_index.all_query(), limit=20, sortedby="freq", reverse=True)

        if results.scored_length() == 0:  # we have no data to show, so show a warning and stop
            wf.add_item('No bookmarks found', 'Try a different query', icon=ICON_WARNING)
            wf.rerun = 1
            wf.send_feedback()
            return 0

        # Loop through the returned bookmarks and add an item for each to
        # the list of results for Alfred
        for hit in results[0:20]:
            encoded_params = "%s,%s,%s" % (hit['profile'], hit['title'], hit['url'])
            wf.add_item(title=hit['title'],
                        subtitle="%d webpages (%d)" % (hit['urlSize'], hit['freq']),
                        arg=encoded_params,
                        valid=True,
                        icon=hit['icon'])

    ####################################################################
    # Reindex in background, if our index was old
    ####################################################################
    fresh_index = wf.cached_data(INDEX_FRESH_CACHE, max_age=300)
    if fresh_index is None:
        wf.logger.info("Index outdated, reindexing")
        run_in_background(BACKGROUND_JOB_KEY,
                          ['/usr/bin/python',
                           wf.workflowfile(UPDATE_INDEX_COMMAND)])

    wf.send_feedback()
    return 0


if __name__ == u"__main__":
    workflow = Workflow3(help_url=HELP_URL,
                         update_settings=UPDATE_SETTINGS)
    sys.exit(workflow.run(main))
