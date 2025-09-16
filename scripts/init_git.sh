#!/usr/bin/env bash
set -e

if [ -z "$1" ]; then
  echo "Usage: $0 git_remote_url"
  exit 1
fi

REMOTE=$1

# инициализация git
git init
git add .
git commit -m "chore: initial scaffold"

# создаём ветку master и пушим
git branch -M master
git remote add origin $REMOTE
git push -u origin master

# создаём ветку dev и пушим
git checkout -b dev
git push -u origin dev

# возвращаемся на master
git checkout master

echo "Репозиторий и ветки master/dev созданы."
