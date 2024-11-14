#!/usr/bin/env python3
# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re
import sys
from typing import List, Tuple, Optional

_THIS_DIR = os.path.abspath(os.path.dirname(__file__))
# The repo's root directory.
_ROOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))

# Add the repo's root directory for clearer imports.
sys.path.insert(0, _ROOT_DIR)

import metadata.fields.field_types as field_types
import metadata.fields.util as util
import metadata.validation_result as vr

# These licenses are used to verify that code imported to Android complies with
# their licensing requirements. Do not add entries to this list without approval.
# Any licenses added should be valid a SPDX Identifier. For the full list of
# identifiers; see https://spdx.org/licenses/
ALLOWED_SPDX_LICENSES = set([
    "APSL-2.0",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-2-Clause-FreeBSD",
    "BSD-3-Clause",
    "BSD-4-Clause",
    "BSD-4-Clause-UC",
    "BSD-Source-Code",
    "GPL-2.0-with-classpath-exception",
    "MIT",
    "MIT-0",
    "MIT-Modern-Variant",
    "MPL-1.1",
    "MPL-2.0",
    "NCSA",
    "OFL-1.1",
    "SGI-B-2.0",
    "Unicode-3.0",
    "Unicode-DFS-2015",
    "Unicode-DFS-2016",
    "X11",
    "Zlib",
    # Public Domain variants.
    "ISC",
    "ICU",
    "SunPro",
    "BSL-1.0",
])

_PATTERN_VERBOSE_DELIMITER = re.compile(r" and | or | / ")

# Split on the canonical delimiter, or any of the non-canonical delimiters.
_PATTERN_SPLIT_LICENSE = re.compile("{}|{}".format(
    _PATTERN_VERBOSE_DELIMITER.pattern,
    field_types.MetadataField.VALUE_DELIMITER))


def process_license_value(value: str,
                          atomic_delimiter: str) -> List[Tuple[str, bool]]:
    """Process a license field value, which may list multiple licenses.

    Args:
        value: the value to process, which may include both verbose and
               atomic delimiters, e.g. "Apache, 2.0 and MIT and custom"
        atomic_delimiter: the delimiter to use as a final step; values
                          will not be further split after using this
                          delimiter.

    Returns: a list of the constituent licenses within the given value,
             and whether the constituent license is on the allowlist.
             e.g. [("Apache, 2.0", True), ("MIT", True),
                   ("custom", False)]
    """
    # Check if the value is on the allowlist as-is, and thus does not
    # require further processing.
    if is_license_allowlisted(value):
        return [(value, True)]

    breakdown = []
    if re.search(_PATTERN_VERBOSE_DELIMITER, value):
        # Split using the verbose delimiters.
        for component in re.split(_PATTERN_VERBOSE_DELIMITER, value):
            breakdown.extend(
                process_license_value(component.strip(), atomic_delimiter))
    else:
        # Split using the standard value delimiter. This results in
        # atomic values; there is no further splitting possible.
        for atomic_value in value.split(atomic_delimiter):
            atomic_value = atomic_value.strip()
            breakdown.append(
                (atomic_value, is_license_allowlisted(atomic_value)))

    return breakdown


def is_license_allowlisted(value: str) -> bool:
    """Returns whether the value is in the allowlist for license
    types.
    """
    return value in ALLOWED_SPDX_LICENSES


class LicenseField(field_types.SingleLineTextField):
    """Custom field for the package's license type(s).

    e.g. Apache 2.0, MIT, BSD, Public Domain.
    """

    def __init__(self):
        super().__init__(name="License")

    def validate(self, value: str) -> Optional[vr.ValidationResult]:
        """Checks the given value consists of recognized license types.

        Note: this field supports multiple values.
        """
        not_allowlisted = []
        licenses = process_license_value(value,
                                         atomic_delimiter=self.VALUE_DELIMITER)
        for license, allowed in licenses:
            if util.is_empty(license):
                return vr.ValidationError(
                    reason=f"{self._name} has an empty value.")
            if not allowed:
                not_allowlisted.append(license)

        if not_allowlisted:
            return vr.ValidationWarning(
                reason=f"{self._name} has a license not in the allowlist.",
                additional=[
                    "Licenses not allowlisted: "
                    f"{util.quoted(not_allowlisted)}.",
                ],
            )

        return None

    def narrow_type(self, value: str) -> Optional[List[str]]:
        if not value:
            # Empty License field is equivalent to "not declared".
            return None

        parts = _PATTERN_SPLIT_LICENSE.split(value)
        return list(filter(bool, map(lambda str: str.strip(), parts)))
