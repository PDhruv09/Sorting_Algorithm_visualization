# Java Sorting Visualizer — Full-Stack Runner

This version changes the original GitHub Pages visualizer from a pattern-matching demo into a tool that **compiles and executes the Java code the user actually submits**.

## What changed

The old version guessed the sorting algorithm and then ran a built-in JavaScript implementation. This version sends the submitted Java to a backend runner that:

1. Finds a supported sorting method.
2. Adds lightweight trace hooks when the source shape can be instrumented safely.
3. Compiles the Java with `javac`.
4. Executes the compiled method on the requested input array.
5. Returns the real final array, stdout, compiler errors, runtime exceptions, timeouts, and trace steps.
6. Uses those trace steps in the existing visualizer.

The algorithm-selection buttons are now informational only. They never replace the submitted Java implementation.

## Supported method shapes

The runner accepts a full Java class or a pasted method. The target method must currently take exactly one of these parameter types:

```java
public static void sort(int[] arr) { ... }
```

or

```java
public static void sort(ArrayList<Integer> arr) { ... }
```

The method can have another name such as `insertionSort`, `quickSort`, `selectionSort`, `bubbleSort`, `mergeSort`, `bucketSort`, `countSort`, or `countingSort`. If several supported methods exist, enter the method name in the UI.

Instance methods are supported as long as the containing class has a no-argument constructor.

## Error reporting

The runner distinguishes:

- compilation errors from `javac`
- runtime exceptions from the student's Java
- execution timeouts / likely infinite loops
- server/validation errors
- successful execution

Compiler messages and Java stack traces are shown in the UI.

## Visualization fidelity

The Java method itself is always what gets compiled and executed. Intermediate visualization is produced by lightweight source instrumentation. It works best with normal course-style Java formatting:

- one statement per line
- braces around `if`, `for`, and `while` bodies
- array/list modifications inside the target method

If the source compiles but cannot be instrumented safely, the runner retries the original source. The actual Java still executes and the final output/error remains authoritative; the UI reports that intermediate tracing is unavailable.

`comparisons` and `array accesses` are trace-derived estimates. The **final Java result and Java errors are actual execution results**.

## Local run

Phase 2 Challenge Mode setup, private roster management, saving behavior, and
tests are documented in [docs/phase2.md](docs/phase2.md). The feature is opt-in
for local testing and does not change the Java execution pipeline.

Requirements:

- Python 3.11+
- Java/JDK 21 (or compatible modern JDK)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

Open `http://localhost:8000`.

## Docker

```bash
docker compose up --build
```

Then open `http://localhost:8000`.

Local Compose enables Challenge Mode with a persistent database volume. Authorize
student emails using `docker compose exec sorting-visualizer python3 challenge_roster.py student@ucsd.edu`.
The container uses its own allowlist; it does not copy the host database. See
[Phase 2 Docker setup](docs/phase2.md#local-docker-testing) for alternate ports and data persistence.

## Important deployment/security note

This repository executes submitted Java code. The included runner applies time, memory, process, file-size, and API restrictions, and `docker-compose.yml` drops Linux capabilities and makes the application filesystem read-only. **This is still not a complete hostile-code sandbox.**

For a public internet deployment, put each execution into a disposable isolated container/microVM with networking disabled and strict CPU/memory/PID/filesystem limits. Do not expose unrestricted host-side `javac/java` execution to untrusted public traffic.

For a DSC 30 staff/internal tool or controlled classroom deployment, this repository is a strong starting point, but the production hosting environment should still isolate execution jobs.

## Project structure

```text
.
├── server.py             FastAPI web server
├── runner.py             Java compile/run/instrumentation layer
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── static/
    ├── index.html
    ├── main.js
    └── style.css
```

## API

`POST /api/execute`

Example:

```json
{
  "code": "public static void sort(int[] arr) { ... }",
  "inputArray": [5, 1, 4, 2, 8],
  "methodName": "sort"
}
```

Successful responses include the detected class/method, final array, stdout/stderr, and trace steps. Failed responses identify compilation errors, runtime exceptions, or timeouts.

## Phase 2 Azure SQL update

See [Azure deployment steps](docs/azure-deployment.md) for the managed-identity
connection, manual schema/grants, and Container App settings. Version 3 uses
only insertion, selection, quick and merge sort, with 15 questions worth one
visible point each when both identification and reasoning are correct. Internal
half-point credit is stored privately for a later grading decision. Detailed
feedback stays hidden until staff release it; release does not expose internal
credit or change scores. Local development still uses SQLite. Deploy the new
image with `CHALLENGE_TEST_VERSION=sorting-15-v3`; older attempts remain preserved.
