from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

COMPILE_TIMEOUT = 6
RUN_TIMEOUT = 3
MAX_OUTPUT = 30_000
MAX_STEPS = 10_000

FORBIDDEN = [
    r"\bpackage\s+",
    r"\bjava\.net\b",
    r"\bjava\.nio\.file\b",
    r"\bFile(?:Input|Output)?Stream\b",
    r"\bFileReader\b|\bFileWriter\b|\bRandomAccessFile\b",
    r"\bProcessBuilder\b",
    r"Runtime\s*\.\s*getRuntime",
    r"System\s*\.\s*exit",
    r"\bClassLoader\b",
    r"\bjava\.lang\.reflect\b",
    r"\bnative\b",
    r"\bThread\b|\bExecutorService\b|\bForkJoinPool\b",
]

@dataclass
class MethodInfo:
    class_name: str
    method_name: str
    is_static: bool
    parameter_kind: str  # int_array | array_list
    array_var: str
    wrapped_method_only: bool


def _reject_dangerous_source(code: str) -> None:
    for pattern in FORBIDDEN:
        if re.search(pattern, code):
            raise ValueError(
                "This runner blocks file/network/process/thread/reflection APIs. "
                f"Blocked pattern: {pattern}"
            )


def _detect_class_name(code: str) -> str | None:
    m = re.search(r"\bpublic\s+class\s+(\w+)", code)
    if not m:
        m = re.search(r"\bclass\s+(\w+)", code)
    return m.group(1) if m else None


def _method_candidates(code: str):
    # Educational subset: void/int[]/ArrayList return; one int[] or ArrayList<Integer> parameter.
    pattern = re.compile(
        r"(?P<prefix>(?:public|private|protected|static|final|synchronized|\s)+)?"
        r"(?P<ret>void|int\s*\[\s*\]|ArrayList\s*<\s*Integer\s*>)\s+"
        r"(?P<name>\w+)\s*\(\s*"
        r"(?P<ptype>int\s*\[\s*\]|ArrayList\s*<\s*Integer\s*>)\s+"
        r"(?P<var>\w+)\s*\)\s*\{",
        re.MULTILINE,
    )
    return list(pattern.finditer(code))


def _prepare_source(code: str, method_name: str | None) -> tuple[str, MethodInfo]:
    code = code.strip()
    _reject_dangerous_source(code)

    class_name = _detect_class_name(code)
    wrapped = False
    if class_name is None:
        # Treat pasted text as a method / methods.
        class_name = "StudentSort"
        code = "import java.util.*;\npublic class StudentSort {\n" + code + "\n}\n"
        wrapped = True

    candidates = _method_candidates(code)
    if not candidates:
        raise ValueError(
            "Could not find a supported sorting method. Use a method with exactly one "
            "int[] or ArrayList<Integer> parameter, for example: "
            "public static void sort(int[] arr) { ... }"
        )

    chosen = None
    if method_name:
        chosen = next((m for m in candidates if m.group("name") == method_name), None)
        if chosen is None:
            raise ValueError(f"No supported method named '{method_name}' was found.")
    else:
        preferred = ["sort", "insertionSort", "quickSort", "selectionSort", "bubbleSort", "mergeSort", "bucketSort", "countSort", "countingSort"]
        for name in preferred:
            chosen = next((m for m in candidates if m.group("name") == name), None)
            if chosen:
                break
        chosen = chosen or candidates[0]

    ptype = re.sub(r"\s+", "", chosen.group("ptype"))
    kind = "int_array" if ptype.startswith("int[") else "array_list"
    prefix = chosen.group("prefix") or ""
    info = MethodInfo(
        class_name=class_name,
        method_name=chosen.group("name"),
        is_static="static" in prefix.split(),
        parameter_kind=kind,
        array_var=chosen.group("var"),
        wrapped_method_only=wrapped,
    )
    return code, info

def _tracked_parameter_from_method_line(
    raw: str,
    parameter_kind: str,
) -> tuple[str, str] | None:
    """
    Detect a Java method declaration on this line that receives the same
    sortable structure as the selected entry method.

    Returns:
        (method_name, array_variable_name)

    Examples:
        mergeSort(int[] arr)                  -> ("mergeSort", "arr")
        merge(int[] arr, int l, int r)        -> ("merge", "arr")
        quickSort(int[] data, int lo, int hi) -> ("quickSort", "data")
    """

    stripped = raw.strip()

    # Do not mistake control-flow statements for method declarations.
    if re.match(
        r"^(if|for|while|switch|catch|else|do|try)\b",
        stripped,
    ):
        return None

    if "(" not in raw or ")" not in raw or "{" not in raw:
        return None

    # Method name immediately before the parameter list.
    name_match = re.search(
        r"\b(?P<name>[A-Za-z_$][\w$]*)\s*\(",
        raw,
    )

    if not name_match:
        return None

    method_name = name_match.group("name")

    start = raw.find("(", name_match.start())
    end = raw.find(")", start)

    if start < 0 or end < 0:
        return None

    params = raw[start + 1:end]

    if parameter_kind == "int_array":
        param_match = re.search(
            r"\bint\s*\[\s*\]\s+"
            r"(?P<var>[A-Za-z_$][\w$]*)",
            params,
        )
    else:
        param_match = re.search(
            r"\bArrayList\s*<\s*Integer\s*>\s+"
            r"(?P<var>[A-Za-z_$][\w$]*)",
            params,
        )

    if not param_match:
        return None

    return method_name, param_match.group("var")

def _instrument_source(
    code: str,
    info: MethodInfo,
) -> tuple[str, bool, str | None]:
    """
    Lightweight source instrumentation for common teaching-style
    sorting code.

    The selected entry method is still the method invoked by the
    harness. However, tracing is added to every method in the same
    class that accepts the same sortable structure.

    This lets recursive/helper-based algorithms such as Merge Sort
    and Quick Sort continue producing visualization events inside:

        mergeSort(...)
        mergeSortHelper(...)
        merge(...)

    or:

        quickSort(...)
        partition(...)

    Actual Java is still compiled and executed. Instrumentation only
    adds tracing calls.
    """

    lines = code.splitlines()
    out: list[str] = []

    brace_depth = 0

    inside_tracked_method = False
    tracked_method_depth: int | None = None
    tracked_var: str | None = None

    trace_available = True
    reason = None

    for lineno, raw in enumerate(lines, start=1):
        line = raw
        stripped = raw.strip()

        # ----------------------------------------------------------
        # Look for ANY method that accepts the same sortable
        # structure as the selected entry method.
        # ----------------------------------------------------------
        if not inside_tracked_method:
            detected = _tracked_parameter_from_method_line(
                raw,
                info.parameter_kind,
            )

            if detected is not None:
                _, tracked_var = detected

                out.append(line)

                brace_depth += (
                    raw.count("{") -
                    raw.count("}")
                )

                tracked_method_depth = brace_depth
                inside_tracked_method = True

                indent = (
                    re.match(r"\s*", raw).group(0)
                    + "    "
                )

                out.append(
                    f'{indent}'
                    f'TraceRuntime.snapshot('
                    f'{tracked_var}, '
                    f'{lineno}, '
                    f'"method-entry");'
                )

                continue

            out.append(line)

            brace_depth += (
                raw.count("{") -
                raw.count("}")
            )

            continue

        # ----------------------------------------------------------
        # We are inside a method that operates on the tracked array.
        # ----------------------------------------------------------
        assert tracked_var is not None

        # Wrap if/while conditions that directly read the tracked
        # structure.
        if (
            stripped.startswith("if")
            or stripped.startswith("while")
        ) and (
            f"{tracked_var}[" in stripped
            or f"{tracked_var}.get(" in stripped
        ):
            first = line.find("(")

            if first >= 0:
                depth = 0
                close = -1

                for pos in range(
                    first,
                    len(line),
                ):
                    if line[pos] == "(":
                        depth += 1

                    elif line[pos] == ")":
                        depth -= 1

                        if depth == 0:
                            close = pos
                            break

                if close > first:
                    condition = line[
                        first + 1:close
                    ]

                    array_indices = re.findall(
                        rf"{re.escape(tracked_var)}"
                        rf"\s*\[\s*([^\]]+?)\s*\]",
                        condition,
                    )

                    list_indices = re.findall(
                        rf"{re.escape(tracked_var)}"
                        rf"\s*\.get\s*\(\s*([^)]+?)\s*\)",
                        condition,
                    )

                    indices = (
                        array_indices +
                        list_indices
                    )

                    refs = len(indices)

                    index_args = ""

                    if indices:
                        index_args = (
                            ", " +
                            ", ".join(indices)
                        )

                    line = (
                        line[:first + 1]
                        +
                        f"TraceRuntime.condition("
                        f"({condition}), "
                        f"{tracked_var}, "
                        f"{lineno}, "
                        f"{refs}"
                        f"{index_args})"
                        +
                        line[close:]
                    )

        out.append(line)

        # ----------------------------------------------------------
        # Snapshot normal statements so changes to the tracked array
        # become visualization steps.
        # ----------------------------------------------------------
        is_control = re.match(
            r"^(if|for|while|switch|else|do|try|catch|finally)\b",
            stripped,
        )

        has_semicolon = stripped.endswith(";")

        is_return = stripped.startswith(
            "return"
        )

        is_decl_only = bool(
            re.match(
                r"^(?:int|long|double|float|boolean|char|String)"
                r"\s+\w+\s*;",
                stripped,
            )
        )

        if (
            has_semicolon
            and not is_control
            and not is_return
            and not is_decl_only
        ):
            refs = (
                stripped.count(
                    f"{tracked_var}["
                )
                +
                stripped.count(
                    f"{tracked_var}.get("
                )
                +
                stripped.count(
                    f"{tracked_var}.set("
                )
            )

            indent = re.match(
                r"\s*",
                raw,
            ).group(0)

            out.append(
                f'{indent}'
                f'TraceRuntime.snapshot('
                f'{tracked_var}, '
                f'{lineno}, '
                f'"statement", '
                f'{refs});'
            )

        # Update nesting using the ORIGINAL source line.
        brace_depth += (
            raw.count("{") -
            raw.count("}")
        )

        # Leaving this tracked method.
        if (
            tracked_method_depth is not None
            and brace_depth < tracked_method_depth
        ):
            inside_tracked_method = False
            tracked_method_depth = None
            tracked_var = None

    if inside_tracked_method:
        trace_available = False
        reason = (
            "Could not determine the end of a "
            "tracked method for visualization."
        )

    return (
        "\n".join(out) + "\n",
        trace_available,
        reason,
    )


def _trace_runtime_java() -> str:
    return r'''
import java.util.*;

public final class TraceRuntime {
    private static final int MAX_STEPS = 10000;
    private static final List<String> STEPS = new ArrayList<>();
    private static int comparisons = 0;
    private static int swaps = 0;
    private static int arrayAccesses = 0;
    private static int[] previous = null;

    private TraceRuntime() {}

    public static boolean condition(
            boolean result,
            int[] arr,
            int line,
            int refs,
            int... indices) {

        comparisons++;
        arrayAccesses += refs;

        int[] copy = Arrays.copyOf(arr, arr.length);
        record(copy, line, "condition", indices);

        return result;
    }

    public static boolean condition(
            boolean result,
            ArrayList<Integer> arr,
            int line,
            int refs,
            int... indices) {

        comparisons++;
        arrayAccesses += refs;

        int[] copy = new int[arr.size()];
        for (int i = 0; i < arr.size(); i++) {
            copy[i] = arr.get(i);
        }

        record(copy, line, "condition", indices);

        return result;
    }

    public static void snapshot(int[] arr, int line, String event) {
        snapshot(arr, line, event, 0);
    }
    public static void snapshot(ArrayList<Integer> arr, int line, String event) {
        snapshot(arr, line, event, 0);
    }

    public static void snapshot(int[] arr, int line, String event, int refs) {
        arrayAccesses += refs;
        record(Arrays.copyOf(arr, arr.length), line, event);
    }

    public static void snapshot(ArrayList<Integer> arr, int line, String event, int refs) {
        arrayAccesses += refs;
        int[] copy = new int[arr.size()];
        for (int i = 0; i < arr.size(); i++) copy[i] = arr.get(i);
        record(copy, line, event);
    }

    private static void record(int[] now, int line, String event) {
        record(now, line, event, null);
    }

    private static void record(
            int[] now,
            int line,
            String event,
            int[] explicitIndices) {

        if (STEPS.size() >= MAX_STEPS) {
            return;
        }

        String type = event;

        int[] changed;

        if ("condition".equals(event) && explicitIndices != null) {
            changed = explicitIndices;
        } else {
            changed = changedIndices(previous, now);
        }

        if (previous != null
                && changed.length == 2
                && !"condition".equals(event)
                && previous[changed[0]] == now[changed[1]]
                && previous[changed[1]] == now[changed[0]]) {

            swaps++;
            type = "swap";

        } else if (
                previous != null
                && changed.length > 0
                && !"condition".equals(event)) {

            type = "write";
        }

        STEPS.add(toJson(type, now, line, changed));
        previous = Arrays.copyOf(now, now.length);
    }

    private static int[] changedIndices(int[] a, int[] b) {
        if (a == null || a.length != b.length) return new int[0];
        int count = 0;
        for (int i = 0; i < a.length; i++) if (a[i] != b[i]) count++;
        int[] out = new int[count];
        int j = 0;
        for (int i = 0; i < a.length; i++) if (a[i] != b[i]) out[j++] = i;
        return out;
    }

    private static String toJson(String type, int[] arr, int line, int[] changed) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"type\":\"").append(type).append("\",");
        sb.append("\"lineNum\":").append(Math.max(0, line - 1)).append(',');
        sb.append("\"array\":").append(Arrays.toString(arr)).append(',');
        sb.append("\"data\":{\"indices\":").append(Arrays.toString(changed)).append("},");
        sb.append("\"comparisons\":").append(comparisons).append(',');
        sb.append("\"swaps\":").append(swaps).append(',');
        sb.append("\"arrayAccesses\":").append(arrayAccesses);
        sb.append('}');
        return sb.toString();
    }

    public static String dump() {
        return "[" + String.join(",", STEPS) + "]";
    }
}
'''


def _harness_java(info: MethodInfo, values: list[int]) -> str:
    vals = ",".join(str(int(v)) for v in values)
    if info.parameter_kind == "int_array":
        setup = f"int[] data = new int[]{{{vals}}};"
        param_class = "int[].class"
        output_expr = "java.util.Arrays.toString(data)"
    else:
        setup = f"java.util.ArrayList<Integer> data = new java.util.ArrayList<>(java.util.Arrays.asList({vals}));"
        param_class = "java.util.ArrayList.class"
        output_expr = "data.toString()"

    return f'''
import java.lang.reflect.*;
import java.util.*;

public class VisualizerHarness {{
    public static void main(String[] args) throws Exception {{
        {setup}
        TraceRuntime.snapshot(data, 1, "start");
        Class<?> clazz = Class.forName("{info.class_name}");
        Method method = clazz.getDeclaredMethod("{info.method_name}", {param_class});
        method.setAccessible(true);
        Object instance = Modifier.isStatic(method.getModifiers()) ? null : clazz.getDeclaredConstructor().newInstance();
        try {{
            method.invoke(instance, data);
        }} catch (InvocationTargetException ite) {{
            Throwable cause = ite.getCause();
            System.err.println("__USER_EXCEPTION__" + cause.getClass().getName() + ": " + String.valueOf(cause.getMessage()));
            cause.printStackTrace(System.err);
            System.exit(70);
        }}
        TraceRuntime.snapshot(data, 1, "complete");
        System.out.println("__FINAL__" + {output_expr});
        System.out.println("__TRACE__" + TraceRuntime.dump());
    }}
}}
'''


def _limits():
    # Applied to the child process on Unix.
    # This is a safety layer, not a complete sandbox.
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (2_000_000, 2_000_000)
        )
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

        # The JVM needs several internal threads even for small programs.
        # A very low NPROC limit prevents javac/java from starting.
        resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
    except Exception:
        pass


def _run(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(cwd),
    }
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        preexec_fn=_limits if os.name == "posix" else None,
    )


def _extract_payload(stdout: str):
    final = None
    trace = []
    user_stdout = []
    for line in stdout.splitlines():
        if line.startswith("__FINAL__"):
            final = line[len("__FINAL__"):]
        elif line.startswith("__TRACE__"):
            try:
                trace = json.loads(line[len("__TRACE__"):])
            except json.JSONDecodeError:
                trace = []
        else:
            user_stdout.append(line)

    normal_output = "\n".join(user_stdout)
    if len(normal_output) > MAX_OUTPUT:
        normal_output = normal_output[-MAX_OUTPUT:]

    return final, trace, normal_output


def execute_java(code: str, values: list[int], method_name: str | None = None) -> dict:
    if len(values) == 0:
        raise ValueError("Input array must contain at least one integer.")
    if len(values) > 500:
        raise ValueError("Input array is limited to 500 elements.")

    source, info = _prepare_source(code, method_name)
    instrumented, trace_expected, trace_reason = _instrument_source(source, info)

    with tempfile.TemporaryDirectory(prefix="sortviz-") as td:
        work = Path(td)
        student_path = work / f"{info.class_name}.java"
        student_path.write_text(instrumented, encoding="utf-8")
        (work / "TraceRuntime.java").write_text(_trace_runtime_java(), encoding="utf-8")
        (work / "VisualizerHarness.java").write_text(_harness_java(info, values), encoding="utf-8")

        try:
            compiled = _run(
                [
                    "javac",
                    "-J-XX:+UseSerialGC",
                    "-J-XX:ActiveProcessorCount=1",
                    "-encoding",
                    "UTF-8",
                    student_path.name,
                    "TraceRuntime.java",
                    "VisualizerHarness.java",
                ],
                work,
                COMPILE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "type": "compile_timeout", "message": "Compilation exceeded the time limit."}

        # If instrumentation introduced a compile error, retry exact source so the user gets
        # truthful Java execution even when intermediate visualization is unavailable.
        if compiled.returncode != 0:
            original_compile_error = compiled.stderr[-MAX_OUTPUT:]
            student_path.write_text(source, encoding="utf-8")
            try:
                retry = _run(
                    [
                        "javac",
                        "-J-XX:+UseSerialGC",
                        "-J-XX:ActiveProcessorCount=1",
                        "-encoding",
                        "UTF-8",
                        student_path.name,
                        "TraceRuntime.java",
                        "VisualizerHarness.java",
                    ],
                    work,
                    COMPILE_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                return {"success": False, "type": "compile_timeout", "message": "Compilation exceeded the time limit."}
            if retry.returncode != 0:
                return {
                    "success": False,
                    "type": "compile_error",
                    "message": retry.stderr[-MAX_OUTPUT:] or retry.stdout[-MAX_OUTPUT:],
                }
            trace_expected = False
            trace_reason = (
                "The original Java code compiled and executed, but the instrumented "
                "tracing version did not compile.\n\nInstrumentation compiler error:\n"
                + original_compile_error
            )

        try:
            ran = _run(
                [
                    "java",
                    "-Xms16m",
                    "-Xmx128m",
                    "-XX:MaxMetaspaceSize=64m",
                    "-XX:+UseSerialGC",
                    "-XX:ActiveProcessorCount=1",
                    "VisualizerHarness",
                ],
                work,
                RUN_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "type": "timeout",
                "message": f"Execution exceeded {RUN_TIMEOUT} seconds (possible infinite loop or very slow code).",
            }

        final, trace, user_stdout = _extract_payload(ran.stdout)
        if ran.returncode != 0:
            stderr = ran.stderr[-MAX_OUTPUT:]
            if "__USER_EXCEPTION__" in stderr:
                first = stderr.split("__USER_EXCEPTION__", 1)[1]
                return {
                    "success": False,
                    "type": "runtime_error",
                    "message": first,
                    "stdout": user_stdout,
                    "trace": trace[:MAX_STEPS],
                }
            return {
                "success": False,
                "type": "runtime_error",
                "message": stderr or "Java process exited with a non-zero status.",
                "stdout": user_stdout,
                "trace": trace[:MAX_STEPS],
            }

        return {
            "success": True,
            "type": "success",
            "className": info.class_name,
            "methodName": info.method_name,
            "parameterKind": info.parameter_kind,
            "finalArray": final,
            "stdout": user_stdout,
            "stderr": ran.stderr[-MAX_OUTPUT:],
            "trace": trace[:MAX_STEPS],
            "traceAvailable": bool(trace) and trace_expected,
            "traceNote": trace_reason,
        }
