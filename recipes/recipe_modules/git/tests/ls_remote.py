# Copyright 2024 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'git',
]


def RunSteps(api):
  url = api.properties.get('url', 'https://chromium.googlesource.com/v8/v8')
  ref = api.properties.get('ref', 'main')
  name = api.properties.get('name')
  tags = api.properties.get('tags', True)
  branches = api.properties.get('branches', True)

  expected_revision = api.properties.get('expected_revision')

  result = api.git.ls_remote(url, ref, name=name, tags=tags, branches=branches)
  api.assertions.assertEqual(result, expected_revision)


def GenTests(api):

  def mock_ls_remote(ref, revision_refs, retcode=None):
    lines = [f"{revision}\t{ref}" for revision, ref in revision_refs] + ['']

    return api.override_step_data(
        f'Retrieve revision for {ref}',
        api.raw_io.stream_output('\n'.join(lines), retcode=retcode or 0),
    )

  yield api.test(
      'basic',
      api.properties(expected_revision='badc0ffee0ded'),
      mock_ls_remote('main', [('badc0ffee0ded', 'refs/heads/main')]),
      # api.post_process(post_process.DropExpectation),
  )

  # WIP...
