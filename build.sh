#!/bin/bash
# Script to check the alias output
shopt -s expand_aliases

# import some definitions
source env.sh

if ! alias pip2 &>/dev/null
then
  alias pip2="${HOME}/Library/Python/2.7/bin/pip"
fi

pip_install() {
  pkg=$1
  local_directory=$2
  if [ -d "$local_directory" ];
  then
    echo "Skipping installing $pkg"
  else
    pip2 install --target=. $pkg
  fi
}

name=$(basename "$PWD")

# install requirements
pip_install Alfred-Workflow workflow
pip_install Whoosh whoosh

zip -FSr ${name}-${alfred_workflow_version}.alfredworkflow . \
  -x "*.pyc" \
  -x ".*" \
  -x "*/__pycache__/*" \
  -x '*.dist-info/*'
