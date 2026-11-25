"""Record execution provenance without turning a local generation into release evidence."""

import os
import re

import repo_env
from native_seed import contract as c


def development(commit):
    return {'kind': 'development', 'commit': commit}


def verify(value, commit, hosted=False, release=False):
    c.require(type(value) is dict, 'execution-origin', 'execution record required')
    if value.get('kind') == 'development':
        c.fields(value, 'kind commit', 'development execution')
        c.require(not hosted and value['commit'] == commit, 'execution-origin',
                  'local generations are development stamps, not qualification or release evidence')
        return value
    c.fields(value, 'kind commit repository run_id run_attempt workflow_ref runner', 'hosted execution')
    repository = repo_env.read()['DAWN_GITHUB_REPO']
    c.require(value['kind'] == 'hosted-release' and value['commit'] == commit and
              value['repository'] == repository and value['runner'] == 'github-hosted/Linux/X64' and
              all(type(value[k]) is str and re.fullmatch(r'[1-9][0-9]*', value[k])
                  for k in ('run_id', 'run_attempt')) and
              type(value['workflow_ref']) is str and
              re.fullmatch(re.escape(repository) + r'/\.github/workflows/[a-zA-Z0-9_-]+\.yml@refs/[^\s]+',
                           value['workflow_ref']), 'execution-origin', 'invalid hosted execution identity')
    if release:
        c.require(value['workflow_ref'].startswith(repository + '/.github/workflows/release.yml@'),
                  'execution-origin', 'release evidence must originate in the hosted release workflow')
    return value


def hosted(commit, release=False):
    c.require(os.environ.get('GITHUB_ACTIONS') == 'true' and
              os.environ.get('GITHUB_SHA') == commit and
              os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted',
              'execution-origin', 'qualification and release require the hosted release environment')
    value = {'kind': 'hosted-release', 'commit': commit,
             'repository': os.environ.get('GITHUB_REPOSITORY'),
             'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
             'workflow_ref': os.environ.get('GITHUB_WORKFLOW_REF'),
             'runner': '/'.join(os.environ.get(k, '') for k in ('RUNNER_ENVIRONMENT', 'RUNNER_OS', 'RUNNER_ARCH'))}
    return verify(value, commit, hosted=True, release=release)


def current(value, commit, release=False):
    verify(value, commit, hosted=True, release=release)
    actual = hosted(commit, release=release)
    # A failed-job retry consumes the successful native job from an earlier attempt.
    c.require(all(value[k] == actual[k] for k in value if k != 'run_attempt') and
              int(value['run_attempt']) <= int(actual['run_attempt']),
              'execution-origin', 'receipt belongs to another workflow run')
