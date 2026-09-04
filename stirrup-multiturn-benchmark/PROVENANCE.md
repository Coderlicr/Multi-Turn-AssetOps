# Provenance and extraction boundary

This standalone project was extracted from the working implementation based on
IBM AssetOpsBench commit:

```text
aac711fe8defdbd310ca8a6bc6a21547e69036ea
Merge pull request #529 from IBM/upgrade-stirrup-agent-0.2.0
```

The standalone runner, schema, dataset builder, evaluator, paired-control
comparator, and tests are modified/extracted files. They intentionally do not
import the original AssetOpsBench `agent`, `benchmark`, `evaluation`, `llm`,
`observability`, `servers`, Supervisor, or Specialist modules.

Runtime framework dependency:

- Artificial Analysis Stirrup 0.2.x, installed from the package declared in
  `pyproject.toml` rather than vendored.

Bundled third-party data:

- MaintIE manually corrected gold release, 1,076 records.
- Source repository: <https://github.com/nlp-tlp/maintie>
- Pinned source commit: `825e7710e4129598da997276a38b3cb40b200bc2`
- Upstream MIT license and source record are retained under
  `src/stirrup_benchmark/maintie/data/`.

The attached Chinese work guide is the project specification and is not a
runtime dependency, so it is not copied into this executable bundle.

