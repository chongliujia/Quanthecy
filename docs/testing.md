# Reproducible checks / 可重复运行的检查

The supported baseline needs Docker Engine, Docker Compose and Make. It does not
depend on a host Python virtual environment, Rust cache, Node installation, local
`.env`, or running application services. Dependency installation uses the committed
`uv.lock`, `Cargo.lock`, and `package-lock.json`; the first build needs registry
access. Base images follow the versions in the existing Dockerfiles.

```bash
make check
make test-down
```

Run cleanup even if a check fails. It only removes the `quanthecy-tests` stack.
Do not run concurrent baseline invocations on the same Docker daemon because they
share this project name. Runtime tests use an internal Docker network with no
outbound access. Image builds still need network access.

| Command | Checks |
| --- | --- |
| `make check-python` | Ruff lint/format, mypy, Django system checks, migration consistency |
| `make test-python` | All Python/Django tests, including the five opt-in ClickHouse integration tests |
| `make check-contracts` | Generated observation contract matches the committed JSON Schema |
| `make test-rust` | Release compilation, rustfmt, Clippy with denied warnings, unit/integration tests |
| `make test-web` | TypeScript, Vite production build, ESLint and Vitest |
| `make test-down` | Remove only disposable test containers and their network |

Python commands build from current source before running. The standalone
`compose.test.yaml` has its own project, image and network, no published host ports,
and memory-backed database storage. It does not merge `compose.override.yaml`, mount
application volumes, run deployment migrations, restart collectors, or run model
workers. Django migrations run against its disposable test database. ClickHouse
tests create uniquely named databases and remove them on completion.

Ruff formatting excludes Django-generated migrations so formatting does not rewrite
released schema history. Migration files still receive lint and migration-consistency
checks; application code and tests receive both lint and formatting checks.
Frontend tests use at most two jsdom workers to bound memory and cold-module
compilation contention on hosts with many CPUs.

For a focused Python rerun after building the test image:

```bash
docker compose --env-file /dev/null -p quanthecy-tests -f compose.test.yaml run --rm -T python pytest -q -p no:cacheprovider tests/test_quality.py tests/test_signal_replay.py tests/test_volume.py
```

Rebuild with `docker compose --env-file /dev/null -p quanthecy-tests -f compose.test.yaml build python`
after editing source; this stack intentionally uses image snapshots, not source
mounts. Exchange and model responses are mocked. No exchange credentials or paid
model calls are required.

The [GitHub workflow](../.github/workflows/checks.yml) uses these same Make targets
for pull requests, main-branch pushes, and manual runs. It also builds each production
image. It has read-only repository permissions and does not deploy or publish images.
Workflow syntax and checkout usage follow the
[GitHub Actions reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
and [checkout documentation](https://github.com/actions/checkout).

中文：运行 `make check` 完成全套检查，结束后（包括失败时）运行 `make test-down`
清理测试环境。已有应用、行情历史和模拟实验不会被测试命令重建或清空。首次构建
需要访问镜像及依赖仓库；不要在同一 Docker 环境同时运行两套基线检查。修改源码后
必须重新构建测试镜像，再执行单项测试。

## Local verification — 20 September 2026

- Python: 473 tests passed in the standalone stack, including all five real
  ClickHouse integration tests and Django tests against PostgreSQL; no skips.
- Rust: 25 tests passed, with rustfmt, Clippy (`-D warnings`) and release compilation.
- Frontend: 102 tests passed with two workers; ESLint, TypeScript and Vite build passed.
- Ruff lint/format, mypy (184 source files), Django system/migration checks and the
  generated contract check passed. Backend, collector and web production images built.
- The original 11 application services remained healthy. No application deployment,
  exchange requests, model requests or application data changes were performed by
  the checks. The GitHub workflow is added but has not yet run on GitHub.

The first full Python run exposed disabled news feature flags in the new test
configuration; enabling those mocked code paths produced the passing run above.
The first frontend container run exposed a one-second cold lazy-module wait under
high worker concurrency; bounded workers and an explicit first-navigation wait
produced the passing container run. No product code changed for either issue.
