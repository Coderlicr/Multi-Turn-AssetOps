# MaintIE upstream data

This directory contains two data files from the official MaintIE repository
(line endings are normalized for this repository):

- `gold_release.json`: the 1,076 manually corrected work-order annotations.
- `scheme.json`: the MaintIE entity and relation scheme.

Source: <https://github.com/nlp-tlp/maintie>

Pinned upstream commit: `825e7710e4129598da997276a38b3cb40b200bc2`

The upstream `LICENSE.md` is retained as `LICENSE.upstream.md`.  The larger
silver corpus and trained model artifacts are deliberately not vendored: the
WTB50 experiment is defined over the gold release, and the MCP server needs no
model weights to query an already annotated IE graph.
