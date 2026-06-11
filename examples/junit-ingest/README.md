# JUnit XML ingest (Java / JS)

Feed test results from any framework that emits standard JUnit XML —
Maven Surefire/Failsafe, Gradle, TestNG, JUnit 5, Jest junit reporter,
Mocha-junit, Playwright's junit reporter, pytest's `--junitxml`, etc.

## Maven / Surefire

```bash
mvn test
qa-dashboard ingest target/surefire-reports/
open captures/run_*/index.html
```

## Gradle

```bash
./gradlew test
qa-dashboard ingest build/test-results/test/
```

## Attach screenshots

If your tests save PNGs next to results, pass `--screenshots-dir`.
Screenshots whose filename or any parent directory name contains the
test method/class name are auto-attached:

```bash
qa-dashboard ingest target/surefire-reports/ \
    --screenshots-dir target/screenshots/
```

## Try it with a sample

```bash
qa-dashboard ingest sample-junit.xml
```

See [sample-junit.xml](sample-junit.xml) in this directory for a tiny
working example.
