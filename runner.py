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

    r"\bThread\b|"

    r"\bExecutorService\b|"

    r"\bForkJoinPool\b",

]





@dataclass

class MethodInfo:

    class_name: str

    method_name: str

    is_static: bool

    parameter_kind: str

    array_var: str

    wrapped_method_only: bool





@dataclass

class TrackedMethod:

    name: str

    array_var: str



    declaration_line: int

    open_line: int

    close_line: int



    heap_size_var: str | None = None



# ============================================================

# Source validation

# ============================================================



def _reject_dangerous_source(

    code: str,

) -> None:

    for pattern in FORBIDDEN:

        if re.search(

            pattern,

            code,

        ):

            raise ValueError(

                "This runner blocks "

                "file/network/process/thread/reflection APIs. "

                f"Blocked pattern: {pattern}"

            )





# ============================================================

# Class detection

# ============================================================



def _detect_class_name(

    code: str,

) -> str | None:

    match = re.search(

        r"\bpublic\s+class\s+(\w+)",

        code,

    )



    if not match:

        match = re.search(

            r"\bclass\s+(\w+)",

            code,

        )



    return (

        match.group(1)

        if match

        else None

    )





# ============================================================

# Entry-method detection

# ============================================================



def _method_candidates(

    code: str,

):

    """

    Locate supported entry methods.



    The entry method itself must take exactly one:



        int[]



    or:



        ArrayList<Integer>



    Helper methods may take additional parameters and are detected

    separately by the tracing system.

    """



    pattern = re.compile(

        r"(?P<prefix>"

        r"(?:"

        r"public|private|protected|static|final|"

        r"synchronized|\s"

        r")+"

        r")?"

        r"(?P<ret>"

        r"void|"

        r"int\s*\[\s*\]|"

        r"ArrayList\s*<\s*Integer\s*>"

        r")"

        r"\s+"

        r"(?P<name>\w+)"

        r"\s*"

        r"\("

        r"\s*"

        r"(?P<ptype>"

        r"int\s*\[\s*\]|"

        r"ArrayList\s*<\s*Integer\s*>"

        r")"

        r"\s+"

        r"(?P<var>\w+)"

        r"\s*"

        r"\)"

        r"\s*"

        r"\{",

        re.MULTILINE,

    )



    return list(

        pattern.finditer(code)

    )





# ============================================================

# Prepare submitted source

# ============================================================



def _prepare_source(

    code: str,

    method_name: str | None,

) -> tuple[str, MethodInfo]:

    code = code.strip()



    _reject_dangerous_source(

        code

    )



    class_name = (

        _detect_class_name(

            code

        )

    )



    wrapped = False



    if class_name is None:

        class_name = (

            "StudentSort"

        )



        code = (

            "import java.util.*;\n"

            "public class StudentSort {\n"

            + code

            + "\n}\n"

        )



        wrapped = True



    candidates = (

        _method_candidates(

            code

        )

    )



    if not candidates:

        raise ValueError(

            "Could not find a supported sorting method. "

            "Use a method with exactly one int[] or "

            "ArrayList<Integer> parameter, for example: "

            "public static void sort(int[] arr) { ... }"

        )



    chosen = None



    if method_name:

        chosen = next(

            (

                candidate

                for candidate

                in candidates

                if candidate.group(

                    "name"

                ) == method_name

            ),

            None,

        )



        if chosen is None:

            raise ValueError(

                f"No supported method named "

                f"'{method_name}' was found."

            )



    else:

        preferred = [

            "sort",

            "insertionSort",

            "selectionSort",

            "mergeSort",

            "quickSort",

            "heapSort",

            "countingSort",

            "countSort",

            "bucketSort",

            "bubbleSort",

        ]



        for name in preferred:

            chosen = next(

                (

                    candidate

                    for candidate

                    in candidates

                    if candidate.group(

                        "name"

                    ) == name

                ),

                None,

            )



            if chosen:

                break



        chosen = (

            chosen

            or candidates[0]

        )



    ptype = re.sub(

        r"\s+",

        "",

        chosen.group(

            "ptype"

        ),

    )



    kind = (

        "int_array"

        if ptype.startswith(

            "int["

        )

        else "array_list"

    )



    prefix = (

        chosen.group(

            "prefix"

        )

        or ""

    )



    info = MethodInfo(

        class_name=class_name,



        method_name=(

            chosen.group(

                "name"

            )

        ),



        is_static=(

            "static"

            in prefix.split()

        ),



        parameter_kind=kind,



        array_var=(

            chosen.group(

                "var"

            )

        ),



        wrapped_method_only=(

            wrapped

        ),

    )



    return code, info





# ============================================================

# Java lexical masking

# ============================================================



def _mask_java_non_code(

    code: str,

) -> str:

    """

    Replace comments, string literals, and character literals with

    spaces while preserving:



        - newlines

        - source length

        - braces

        - parentheses

        - identifiers



    This lets the lightweight parser inspect Java structure without

    accidentally treating braces inside strings/comments as real

    Java syntax.

    """



    output: list[str] = []



    index = 0

    state = "normal"

    escaped = False



    while index < len(code):

        char = code[index]



        next_char = (

            code[index + 1]

            if index + 1

            < len(code)

            else ""

        )



        # --------------------------------------------------------

        # Normal source

        # --------------------------------------------------------



        if state == "normal":

            if (

                char == "/"

                and

                next_char == "/"

            ):

                output.extend(

                    [" ", " "]

                )



                index += 2



                state = (

                    "line_comment"

                )



                continue



            if (

                char == "/"

                and

                next_char == "*"

            ):

                output.extend(

                    [" ", " "]

                )



                index += 2



                state = (

                    "block_comment"

                )



                continue



            if char == '"':

                output.append(

                    " "

                )



                index += 1



                state = "string"

                escaped = False



                continue



            if char == "'":

                output.append(

                    " "

                )



                index += 1



                state = "char"

                escaped = False



                continue



            output.append(

                char

            )



            index += 1



            continue





        # --------------------------------------------------------

        # // comment

        # --------------------------------------------------------



        if (

            state ==

            "line_comment"

        ):

            if char == "\n":

                output.append(

                    "\n"

                )



                state = (

                    "normal"

                )



            else:

                output.append(

                    " "

                )



            index += 1



            continue





        # --------------------------------------------------------

        # /* comment */

        # --------------------------------------------------------



        if (

            state ==

            "block_comment"

        ):

            if (

                char == "*"

                and

                next_char == "/"

            ):

                output.extend(

                    [" ", " "]

                )



                index += 2



                state = (

                    "normal"

                )



                continue



            output.append(

                "\n"

                if char == "\n"

                else " "

            )



            index += 1



            continue





        # --------------------------------------------------------

        # String / char literal

        # --------------------------------------------------------



        if state in {

            "string",

            "char",

        }:

            if char == "\n":

                output.append(

                    "\n"

                )



                index += 1

                escaped = False



                continue



            output.append(

                " "

            )



            if escaped:

                escaped = False



            elif char == "\\":

                escaped = True



            elif (

                state == "string"

                and

                char == '"'

            ):

                state = "normal"



            elif (

                state == "char"

                and

                char == "'"

            ):

                state = "normal"



            index += 1



            continue



    return "".join(

        output

    )





# ============================================================

# Brace matching

# ============================================================



def _find_matching_brace(

    masked: str,

    open_pos: int,

) -> int | None:

    depth = 0



    for position in range(

        open_pos,

        len(masked),

    ):

        char = masked[

            position

        ]



        if char == "{":

            depth += 1



        elif char == "}":

            depth -= 1



            if depth == 0:

                return position



    return None





# ============================================================

# Find all methods operating on the tracked array

# ============================================================



def _tracked_methods(

    code: str,

    parameter_kind: str,

) -> list[TrackedMethod]:

    """

    Find all methods that receive the same sortable structure as

    the selected entry method.



    Unlike the older implementation, this scans the whole source

    rather than requiring a method declaration to exist on one

    physical line.



    Supported examples:



        private static void merge(

            int[] arr,

            int left,

            int right

        ) {



        private static int partition(

            int[] arr,

            int low,

            int high

        ) {



        private static void heapify(

            int[] arr,

            int heapSize,

            int root

        ) {

    """



    masked = (

        _mask_java_non_code(

            code

        )

    )



    method_pattern = re.compile(

        r"(?P<mods>"

        r"(?:"

        r"(?:"

        r"public|private|protected|static|final|"

        r"synchronized|abstract|strictfp"

        r")"

        r"\s+"

        r")*"

        r")"



        r"(?P<rtype>"

        r"(?:"

        r"void|"

        r"[A-Za-z_$][\w$.]*"

        r"(?:"

        r"\s*<[^>{}();]*>"

        r")?"

        r"(?:"

        r"\s*\[\s*\]"

        r")*"

        r")"

        r")"



        r"\s+"



        r"(?P<name>"

        r"[A-Za-z_$][\w$]*"

        r")"



        r"\s*"



        r"\("



        r"(?P<params>"

        r"[^)]*"

        r")"



        r"\)"



        r"(?:"

        r"\s+throws\s+[^{]+"

        r")?"



        r"\s*"



        r"\{",



        re.MULTILINE,

    )



    tracked: list[

        TrackedMethod

    ] = []



    for match in (

        method_pattern

        .finditer(masked)

    ):

        params = (

            match.group(

                "params"

            )

        )



        if (

            parameter_kind ==

            "int_array"

        ):

            param_match = (

                re.search(

                    r"\bint"

                    r"\s*"

                    r"\["

                    r"\s*"

                    r"\]"

                    r"\s+"

                    r"(?P<var>"

                    r"[A-Za-z_$]"

                    r"[\w$]*"

                    r")",

                    params,

                )

            )



        else:

            param_match = (

                re.search(

                    r"\bArrayList"

                    r"\s*"

                    r"<"

                    r"\s*"

                    r"Integer"

                    r"\s*"

                    r">"

                    r"\s+"

                    r"(?P<var>"

                    r"[A-Za-z_$]"

                    r"[\w$]*"

                    r")",

                    params,

                )

            )



        if not param_match:

            continue



        open_pos = (

            match.end() - 1

        )



        close_pos = (

            _find_matching_brace(

                masked,

                open_pos,

            )

        )



        if close_pos is None:

            continue



        declaration_line = (

            masked.count(

                "\n",

                0,

                match.start(

                    "name"

                ),

            )

            + 1

        )



        open_line = (

            masked.count(

                "\n",

                0,

                open_pos,

            )

            + 1

        )



        close_line = (

            masked.count(

                "\n",

                0,

                close_pos,

            )

            + 1

        )



        heap_size_var = None



        if re.search(

            r"\b(?:"

            r"heapify|"

            r"siftDown|"

            r"siftdown|"

            r"sift_down|"

            r"downHeap|"

            r"downheap"

            r")\b",

            match.group("name"),

            re.IGNORECASE,

        ):

            remaining_params = (

                params[

                    param_match.end():

                ]

            )



            size_match = re.search(

                r"\bint\s+"

                r"(?P<name>"

                r"[A-Za-z_$]"

                r"[\w$]*"

                r")",

                remaining_params,

            )



            if size_match:

                heap_size_var = (

                    size_match.group(

                        "name"

                    )

                )



        tracked.append(

            TrackedMethod(

                name=(

                    match.group(

                        "name"

                    )

                ),



                array_var=(

                    param_match.group(

                        "var"

                    )

                ),



                declaration_line=(

                    declaration_line

                ),



                open_line=(

                    open_line

                ),



                close_line=(

                    close_line

                ),

                heap_size_var=(

                    heap_size_var

                ),

            )

        )



    return tracked





# ============================================================

# Same-line condition parsing

# ============================================================



def _find_balanced_condition(

    line: str,

) -> tuple[int, int] | None:

    """

    Find the matching parentheses for a control condition when the

    entire condition exists on this physical line.



    Multiline conditions are still executed and traced through

    surrounding statements, but we deliberately avoid rewriting

    them until the complete expression is known.

    """



    first = line.find(

        "("

    )



    if first < 0:

        return None



    depth = 0



    for position in range(

        first,

        len(line),

    ):

        char = line[

            position

        ]



        if char == "(":

            depth += 1



        elif char == ")":

            depth -= 1



            if depth == 0:

                return (

                    first,

                    position,

                )



    return None





# ============================================================

# Source instrumentation

# ============================================================



def _detect_bucket_write(

    statement: str,

) -> tuple[str, str] | None:

    """

    Recognize a simple 2D-array bucket insertion such as:



        buckets[bucketIndex][bucketSizes[bucketIndex]] = value;



    Returns:



        (bucket_index_expression, value_expression)



    We intentionally only emit an auxiliary event when the bucket

    index and inserted value are simple runtime expressions. The

    actual Java assignment is still authoritative.

    """



    left_side = statement.split(
        "=",
        1,
    )[0]

    # Distribution into a 2D bucket array commonly uses another
    # array access for the current bucket size, e.g.
    # buckets[bucketIndex][bucketSizes[bucketIndex]] = value.
    # Requiring that nested access prevents internal per-bucket
    # sorting writes such as buckets[bucket][j + 1] = key from
    # being mistaken for new bucket insertions.
    if left_side.count("[") < 3:
        return None



    match = re.match(

        r"^\s*"

        r"[A-Za-z_$][\w$]*"

        r"\s*"

        r"\["

        r"\s*(?P<bucket>[^\]]+?)\s*"

        r"\]"

        r"\s*"

        r"\[.*\]"

        r"\s*=\s*"

        r"(?P<value>[^;]+?)"

        r"\s*;"

        r"\s*$",

        statement,

    )



    if not match:

        return None



    bucket_expr = (

        match.group("bucket").strip()

    )



    value_expr = (

        match.group("value").strip()

    )



    # Avoid duplicating expressions with side effects.

    safe_expression = re.compile(

        r"^(?:"

        r"-?\d+|"

        r"[A-Za-z_$][\w$]*"

        r")$"

    )



    if not safe_expression.fullmatch(

        bucket_expr

    ):

        return None



    if not safe_expression.fullmatch(

        value_expr

    ):

        return None



    return (

        bucket_expr,

        value_expr,

    )




def _detect_recent_bucket_write(
    lines: list[str],
    lineno: int,
    method_open_line: int,
) -> tuple[str, str] | None:
    """
    Detect a bucket insertion even when the Java assignment is
    formatted across several physical lines, for example:

        buckets[bucketIndex]
            [bucketSizes[bucketIndex]] =
            value;

    Only a short suffix ending at the current semicolon is examined.
    The submitted Java still performs the real assignment; this helper
    only decides whether to emit the matching auxiliary trace event.
    """

    first_line = max(
        method_open_line + 1,
        lineno - 7,
    )

    for start_line in range(
        lineno,
        first_line - 1,
        -1,
    ):
        statement = " ".join(
            part.strip()
            for part in lines[
                start_line - 1:
                lineno
            ]
            if part.strip()
        )

        match = _detect_bucket_write(
            statement
        )

        if match is not None:
            return match

    return None

def _instrument_source(

    code: str,

    info: MethodInfo,

) -> tuple[

    str,

    bool,

    str | None,

]:

    """

    Add lightweight tracing to methods operating on the submitted

    sortable structure.



    Important properties:



    1. Helper methods are detected across the whole source.

    2. Multiline method declarations are supported.

    3. Multiline for/while/if headers are not mistaken for normal

       statements.

    4. The original Java remains authoritative.

    5. If instrumentation ever causes a compile failure,

       execute_java() retries the exact original Java source.

    """



    lines = (

        code.splitlines()

    )



    masked_lines = (

        _mask_java_non_code(

            code

        )

        .splitlines()

    )



    methods = (

        _tracked_methods(

            code,

            info.parameter_kind,

        )

    )



    if not methods:

        return (

            (

                code

                if code.endswith(

                    "\n"

                )

                else code + "\n"

            ),



            False,



            (

                "No helper or entry method using the "

                "sortable structure could be instrumented."

            ),

        )



    # --------------------------------------------------------

    # Map every source line to its tracked method

    # --------------------------------------------------------



    line_to_method: dict[

        int,

        TrackedMethod,

    ] = {}



    for method in methods:

        for line_number in range(

            method.open_line,

            method.close_line + 1,

        ):

            line_to_method[

                line_number

            ] = method





    output: list[str] = []



    current_method: (

        TrackedMethod | None

    ) = None



    # Parenthesis depth is important because a line such as:

    #

    #     int i = 0;

    #

    # may actually be part of:

    #

    #     for (

    #         int i = 0;

    #         ...

    #     )

    #

    # and must NOT have a trace statement inserted after it.

    paren_depth = 0





    for lineno, raw in enumerate(

        lines,

        start=1,

    ):

        masked_raw = (

            masked_lines[

                lineno - 1

            ]

            if lineno - 1

            < len(masked_lines)

            else raw

        )



        stripped = (

            raw.strip()

        )



        method = (

            line_to_method.get(

                lineno

            )

        )





        # ----------------------------------------------------

        # Outside any tracked sorting/helper method

        # ----------------------------------------------------



        if method is None:

            current_method = None

            paren_depth = 0



            output.append(

                raw

            )



            continue





        # ----------------------------------------------------

        # Entering a tracked method

        # ----------------------------------------------------



        if (

            current_method

            is not method

        ):

            current_method = (

                method

            )



            paren_depth = 0





        # ----------------------------------------------------

        # Method opening brace

        # ----------------------------------------------------



        if (

            lineno ==

            method.open_line

        ):

            output.append(

                raw

            )



            indent = (

                re.match(

                    r"\s*",

                    raw,

                ).group(0)

                + "    "

            )



            output.append(

                f'{indent}'

                f'TraceRuntime.snapshot('

                f'{method.array_var}, '

                f'{method.declaration_line}, '

                f'"method-entry");'

            )



            if (

                method.heap_size_var

                is not None

            ):

                output.append(

                    f'{indent}'

                    f'TraceRuntime.heapBoundary('

                    f'{method.array_var}, '

                    f'{method.declaration_line}, '

                    f'{method.heap_size_var}'

                    f');'

                )



            continue





        # ----------------------------------------------------

        # Method closing brace

        # ----------------------------------------------------



        if (

            lineno ==

            method.close_line

        ):

            output.append(

                raw

            )



            current_method = None

            paren_depth = 0



            continue





        tracked_var = (

            method.array_var

        )



        line = raw



        at_top_level = (

            paren_depth == 0

        )





        # ----------------------------------------------------

        # Same-line IF / WHILE condition tracing

        # ----------------------------------------------------



        if (

            at_top_level

            and

            re.match(

                r"^\s*(if|while)\b",

                masked_raw,

            )

        ):

            bounds = (

                _find_balanced_condition(

                    masked_raw

                )

            )



            if bounds is not None:

                first, close = (

                    bounds

                )



                condition = (

                    raw[

                        first + 1:

                        close

                    ]

                )



                if (

                    f"{tracked_var}["

                    in condition

                    or

                    f"{tracked_var}.get("

                    in condition

                ):

                    array_indices = (

                        re.findall(

                            rf"{re.escape(tracked_var)}"

                            rf"\s*"

                            rf"\["

                            rf"\s*"

                            rf"([^\]]+?)"

                            rf"\s*"

                            rf"\]",

                            condition,

                        )

                    )



                    list_indices = (

                        re.findall(

                            rf"{re.escape(tracked_var)}"

                            rf"\s*"

                            rf".get"

                            rf"\s*"

                            rf"\("

                            rf"\s*"

                            rf"([^)]+?)"

                            rf"\s*"

                            rf"\)",

                            condition,

                        )

                    )



                    indices = (

                        array_indices

                        +

                        list_indices

                    )



                    refs = len(

                        indices

                    )



                    index_args = ""



                    if indices:

                        index_args = (

                            ", "

                            +

                            ", ".join(

                                indices

                            )

                        )



                    line = (

                        raw[

                            :first + 1

                        ]

                        +

                        (

                            "TraceRuntime.condition("

                            f"({condition}), "

                            f"{tracked_var}, "

                            f"{lineno}, "

                            f"{refs}"

                            f"{index_args}"

                            ")"

                        )

                        +

                        raw[

                            close:

                        ]

                    )





        output.append(

            line

        )





        # ----------------------------------------------------

        # Parenthesis state

        # ----------------------------------------------------



        delta = (

            masked_raw.count(

                "("

            )

            -

            masked_raw.count(

                ")"

            )

        )



        next_paren_depth = (

            max(

                0,

                paren_depth

                + delta,

            )

        )





        # ----------------------------------------------------

        # Determine whether this is a safe standalone statement

        # ----------------------------------------------------



        is_control = bool(

            re.match(

                r"^\s*"

                r"(?:"

                r"if|for|while|switch|"

                r"else|do|try|catch|finally"

                r")"

                r"\b",

                masked_raw,

            )

        )



        has_semicolon = (

            stripped.endswith(

                ";"

            )

        )



        # Inserting a trace after these can produce unreachable

        # Java code.

        is_jump = bool(

            re.match(

                r"^(?:"

                r"return|break|continue|throw"

                r")"

                r"\b",

                stripped,

            )

        )



        # A declaration without initialization does not change

        # interesting runtime state.

        is_decl_only = bool(

            re.match(

                r"^(?:"

                r"int|long|double|float|"

                r"boolean|char|String"

                r")"

                r"\s+"

                r"\w+"

                r"\s*"

                r";",

                stripped,

            )

        )





        # ----------------------------------------------------

        # Snapshot safe standalone statements

        # ----------------------------------------------------



        if (

            at_top_level

            and

            next_paren_depth == 0

            and

            has_semicolon

            and

            not is_control

            and

            not is_jump

            and

            not is_decl_only

        ):

            bucket_write = (

                _detect_recent_bucket_write(

                    lines,

                    lineno,

                    method.open_line,

                )

            )



            indent = (

                re.match(

                    r"\s*",

                    raw,

                ).group(0)

            )



            # ---------------------------------------------------------

            # Special auxiliary event for actual Bucket Sort insertion.

            # ---------------------------------------------------------



            if(

                bucket_write

                is not None

            ):

                (

                    bucket_index_expr,

                    bucket_value_expr,

                ) = bucket_write

                output.append(

                    f'{indent}'

                    f'TraceRuntime.bucketWrite('

                    f'{tracked_var}, '

                    f'{lineno}, '

                    f'{bucket_index_expr}, '

                    f'{bucket_value_expr}'

                    f');'

                )

            else:

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



                output.append(

                    f'{indent}'

                    f'TraceRuntime.snapshot('

                    f'{tracked_var}, '

                    f'{lineno}, '

                    f'"statement", '

                    f'{refs});'

                )



        paren_depth = (

            next_paren_depth

        )





    return (

        "\n".join(

            output

        )

        + "\n",



        True,



        None,

    )





# ============================================================

# Java tracing runtime

# ============================================================



def _trace_runtime_java() -> str:

    return r'''

import java.util.*;



public final class TraceRuntime {

    private static final int MAX_STEPS = 10000;



    private static final List<String> STEPS =

        new ArrayList<>();



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



        int[] copy =

            Arrays.copyOf(

                arr,

                arr.length

            );



        record(

            copy,

            line,

            "condition",

            indices

        );



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



        int[] copy =

            new int[

                arr.size()

            ];



        for (

            int i = 0;

            i < arr.size();

            i++

        ) {

            copy[i] =

                arr.get(i);

        }



        record(

            copy,

            line,

            "condition",

            indices

        );



        return result;

    }





    public static void snapshot(

            int[] arr,

            int line,

            String event) {



        snapshot(

            arr,

            line,

            event,

            0

        );

    }





    public static void snapshot(

            ArrayList<Integer> arr,

            int line,

            String event) {



        snapshot(

            arr,

            line,

            event,

            0

        );

    }





    public static void snapshot(

            int[] arr,

            int line,

            String event,

            int refs) {



        arrayAccesses += refs;



        record(

            Arrays.copyOf(

                arr,

                arr.length

            ),

            line,

            event

        );

    }





    public static void snapshot(

            ArrayList<Integer> arr,

            int line,

            String event,

            int refs) {



        arrayAccesses += refs;



        int[] copy =

            new int[

                arr.size()

            ];



        for (

            int i = 0;

            i < arr.size();

            i++

        ) {

            copy[i] =

                arr.get(i);

        }



        record(

            copy,

            line,

            event

        );

    }



    public static void heapBoundary(

            int[] arr,

            int line,

            int heapSize) {



        int[] copy =

            Arrays.copyOf(

                arr,

                arr.length

            );



        recordHeapBoundary(

            copy,

            line,

            heapSize

        );

    }





    public static void heapBoundary(

            ArrayList<Integer> arr,

            int line,

            int heapSize) {



        int[] copy =

            new int[

                arr.size()

            ];



        for (

            int i = 0;

            i < arr.size();

            i++

        ) {

            copy[i] =

                arr.get(i);

        }



        recordHeapBoundary(

            copy,

            line,

            heapSize

        );

    }





    private static void recordHeapBoundary(

            int[] now,

            int line,

            int heapSize) {



        if (

            STEPS.size()

            >=

            MAX_STEPS

        ) {

            return;

        }



        heapSize =

            Math.max(

                0,

                Math.min(

                    heapSize,

                    now.length

                )

            );



        StringBuilder builder =

            new StringBuilder();



        builder.append(

            "{\"type\":\"heap-boundary\","

        );



        builder

            .append(

                "\"lineNum\":"

            )

            .append(

                Math.max(

                    0,

                    line - 1

                )

            )

            .append(',');



        builder

            .append(

                "\"array\":"

            )

            .append(

                Arrays.toString(

                    now

                )

            )

            .append(',');



        builder

            .append(

                "\"data\":{"

            )

            .append(

                "\"indices\":[],"

            )

            .append(

                "\"heapSize\":"

            )

            .append(

                heapSize

            )

            .append(

                "},"

            );



        builder

            .append(

                "\"comparisons\":"

            )

            .append(

                comparisons

            )

            .append(',');



        builder

            .append(

                "\"swaps\":"

            )

            .append(

                swaps

            )

            .append(',');



        builder

            .append(

                "\"arrayAccesses\":"

            )

            .append(

                arrayAccesses

            );



        builder.append(

            '}'

        );



        STEPS.add(

            builder.toString()

        );

    }



    public static void bucketWrite(

            int[] arr,

            int line,

            int bucketIndex,

            int value) {



        int[] copy =

            Arrays.copyOf(

                arr,

                arr.length

            );



        recordBucket(

            copy,

            line,

            bucketIndex,

            value

        );

    }





    public static void bucketWrite(

            ArrayList<Integer> arr,

            int line,

            int bucketIndex,

            int value) {



        int[] copy =

            new int[

                arr.size()

            ];



        for (

            int i = 0;

            i < arr.size();

            i++

        ) {

            copy[i] =

                arr.get(i);

        }



        recordBucket(

            copy,

            line,

            bucketIndex,

            value

        );

    }





    private static void recordBucket(

            int[] now,

            int line,

            int bucketIndex,

            int value) {



        if (

            STEPS.size()

            >=

            MAX_STEPS

        ) {

            return;

        }



        StringBuilder builder =

            new StringBuilder();



        builder

            .append(

                "{\"type\":\"bucket-write\","

            );



        builder

            .append(

                "\"lineNum\":"

            )

            .append(

                Math.max(

                    0,

                    line - 1

                )

            )

            .append(',');



        builder

            .append(

                "\"array\":"

            )

            .append(

                Arrays.toString(

                    now

                )

            )

            .append(',');



        builder

            .append(

                "\"data\":{"

            )

            .append(

                "\"indices\":[],"

            )

            .append(

                "\"bucketIndex\":"

            )

            .append(

                bucketIndex

            )

            .append(',')

            .append(

                "\"value\":"

            )

            .append(

                value

            )

            .append(

                "},"

            );



        builder

            .append(

                "\"comparisons\":"

            )

            .append(

                comparisons

            )

            .append(',');



        builder

            .append(

                "\"swaps\":"

            )

            .append(

                swaps

            )

            .append(',');



        builder

            .append(

                "\"arrayAccesses\":"

            )

            .append(

                arrayAccesses

            );



        builder.append(

            '}'

        );



        STEPS.add(

            builder.toString()

        );



        previous =

            Arrays.copyOf(

                now,

                now.length

            );

    }



    private static void record(

            int[] now,

            int line,

            String event) {



        record(

            now,

            line,

            event,

            null

        );

    }





    private static void record(

            int[] now,

            int line,

            String event,

            int[] explicitIndices) {



        if (

            STEPS.size()

            >=

            MAX_STEPS

        ) {

            return;

        }



        String type =

            event;



        int[] changed;



        if (

            "condition".equals(

                event

            )

            &&

            explicitIndices != null

        ) {

            changed =

                explicitIndices;



        } else {

            changed =

                changedIndices(

                    previous,

                    now

                );

        }





        if (

            previous != null

            &&

            changed.length == 2

            &&

            !"condition".equals(

                event

            )

            &&

            previous[

                changed[0]

            ]

            ==

            now[

                changed[1]

            ]

            &&

            previous[

                changed[1]

            ]

            ==

            now[

                changed[0]

            ]

        ) {

            swaps++;



            type =

                "swap";



        } else if (

            previous != null

            &&

            changed.length > 0

            &&

            !"condition".equals(

                event

            )

        ) {

            type =

                "write";

        }





        STEPS.add(

            toJson(

                type,

                now,

                line,

                changed

            )

        );



        previous =

            Arrays.copyOf(

                now,

                now.length

            );

    }





    private static int[] changedIndices(

            int[] first,

            int[] second) {



        if (

            first == null

            ||

            first.length

            !=

            second.length

        ) {

            return new int[0];

        }



        int count = 0;



        for (

            int i = 0;

            i < first.length;

            i++

        ) {

            if (

                first[i]

                !=

                second[i]

            ) {

                count++;

            }

        }



        int[] output =

            new int[

                count

            ];



        int position = 0;



        for (

            int i = 0;

            i < first.length;

            i++

        ) {

            if (

                first[i]

                !=

                second[i]

            ) {

                output[

                    position++

                ] = i;

            }

        }



        return output;

    }





    private static String toJson(

            String type,

            int[] arr,

            int line,

            int[] changed) {



        StringBuilder builder =

            new StringBuilder();



        builder

            .append(

                "{\"type\":\""

            )

            .append(

                type

            )

            .append(

                "\","

            );



        builder

            .append(

                "\"lineNum\":"

            )

            .append(

                Math.max(

                    0,

                    line - 1

                )

            )

            .append(',');



        builder

            .append(

                "\"array\":"

            )

            .append(

                Arrays.toString(

                    arr

                )

            )

            .append(',');



        builder

            .append(

                "\"data\":{\"indices\":"

            )

            .append(

                Arrays.toString(

                    changed

                )

            )

            .append(

                "},"

            );



        builder

            .append(

                "\"comparisons\":"

            )

            .append(

                comparisons

            )

            .append(',');



        builder

            .append(

                "\"swaps\":"

            )

            .append(

                swaps

            )

            .append(',');



        builder

            .append(

                "\"arrayAccesses\":"

            )

            .append(

                arrayAccesses

            );



        builder.append(

            '}'

        );



        return builder.toString();

    }





    public static String dump() {

        return (

            "["

            +

            String.join(

                ",",

                STEPS

            )

            +

            "]"

        );

    }

}

'''





# ============================================================

# Java harness

# ============================================================



def _harness_java(

    info: MethodInfo,

    values: list[int],

) -> str:

    vals = ",".join(

        str(int(value))

        for value in values

    )



    if (

        info.parameter_kind

        ==

        "int_array"

    ):

        setup = (

            f"int[] data = "

            f"new int[]{{{vals}}};"

        )



        param_class = (

            "int[].class"

        )



        output_expr = (

            "java.util.Arrays"

            ".toString(data)"

        )



    else:

        setup = (

            "java.util.ArrayList<Integer> data = "

            "new java.util.ArrayList<>("

            "java.util.Arrays.asList("

            f"{vals}"

            "));"

        )



        param_class = (

            "java.util.ArrayList.class"

        )



        output_expr = (

            "data.toString()"

        )



    return f'''

import java.lang.reflect.*;

import java.util.*;



public class VisualizerHarness {{



    public static void main(

            String[] args)

            throws Exception {{



        {setup}



        TraceRuntime.snapshot(

            data,

            1,

            "start"

        );



        Class<?> clazz =

            Class.forName(

                "{info.class_name}"

            );



        Method method =

            clazz.getDeclaredMethod(

                "{info.method_name}",

                {param_class}

            );



        method.setAccessible(

            true

        );



        Object instance =

            Modifier.isStatic(

                method.getModifiers()

            )

                ? null

                : clazz

                    .getDeclaredConstructor()

                    .newInstance();



        try {{

            method.invoke(

                instance,

                data

            );



        }} catch (

            InvocationTargetException ite

        ) {{

            Throwable cause =

                ite.getCause();



            System.err.println(

                "__USER_EXCEPTION__"

                +

                cause

                    .getClass()

                    .getName()

                +

                ": "

                +

                String.valueOf(

                    cause.getMessage()

                )

            );



            cause.printStackTrace(

                System.err

            );



            System.exit(

                70

            );

        }}



        TraceRuntime.snapshot(

            data,

            1,

            "complete"

        );



        System.out.println(

            "__FINAL__"

            +

            {output_expr}

        );



        System.out.println(

            "__TRACE__"

            +

            TraceRuntime.dump()

        );

    }}

}}

'''





# ============================================================

# Child-process limits

# ============================================================



def _limits():

    """

    Applied to child javac/java processes on Unix.



    This is a safety layer, not a complete hostile-code sandbox.

    """



    try:

        resource.setrlimit(

            resource.RLIMIT_CPU,

            (

                3,

                3,

            ),

        )



        resource.setrlimit(

            resource.RLIMIT_FSIZE,

            (

                2_000_000,

                2_000_000,

            ),

        )



        resource.setrlimit(

            resource.RLIMIT_NOFILE,

            (

                64,

                64,

            ),

        )



        # JVM requires several internal threads.

        resource.setrlimit(

            resource.RLIMIT_NPROC,

            (

                128,

                128,

            ),

        )



    except Exception:

        pass





# ============================================================

# Process runner

# ============================================================



def _run(

    cmd: list[str],

    cwd: Path,

    timeout: int,

) -> subprocess.CompletedProcess[str]:

    env = {

        "PATH":

            os.environ.get(

                "PATH",

                "",

            ),



        "LANG":

            "C.UTF-8",



        "LC_ALL":

            "C.UTF-8",



        "HOME":

            str(cwd),

    }



    return subprocess.run(

        cmd,



        cwd=cwd,



        capture_output=True,



        text=True,



        timeout=timeout,



        env=env,



        preexec_fn=(

            _limits

            if os.name == "posix"

            else None

        ),

    )





# ============================================================

# Runner-output extraction

# ============================================================



def _extract_payload(

    stdout: str,

):

    final = None

    trace = []



    user_stdout: list[str] = []



    for line in (

        stdout.splitlines()

    ):

        if line.startswith(

            "__FINAL__"

        ):

            final = line[

                len(

                    "__FINAL__"

                ):

            ]



        elif line.startswith(

            "__TRACE__"

        ):

            try:

                trace = json.loads(

                    line[

                        len(

                            "__TRACE__"

                        ):

                    ]

                )



            except json.JSONDecodeError:

                trace = []



        else:

            user_stdout.append(

                line

            )



    normal_output = (

        "\n".join(

            user_stdout

        )

    )



    if (

        len(normal_output)

        >

        MAX_OUTPUT

    ):

        normal_output = (

            normal_output[

                -MAX_OUTPUT:

            ]

        )



    return (

        final,

        trace,

        normal_output,

    )





# ============================================================

# Public execution function

# ============================================================



def execute_java(

    code: str,

    values: list[int],

    method_name: str | None = None,

) -> dict:

    if len(values) == 0:

        raise ValueError(

            "Input array must contain "

            "at least one integer."

        )



    if len(values) > 500:

        raise ValueError(

            "Input array is limited "

            "to 500 elements."

        )





    source, info = (

        _prepare_source(

            code,

            method_name,

        )

    )





    (

        instrumented,

        trace_expected,

        trace_reason,

    ) = _instrument_source(

        source,

        info,

    )





    with tempfile.TemporaryDirectory(

        prefix="sortviz-"

    ) as temp_directory:

        work = Path(

            temp_directory

        )



        student_path = (

            work

            /

            f"{info.class_name}.java"

        )





        # ----------------------------------------------------

        # Write instrumented source first

        # ----------------------------------------------------



        student_path.write_text(

            instrumented,

            encoding="utf-8",

        )



        (

            work

            /

            "TraceRuntime.java"

        ).write_text(

            _trace_runtime_java(),

            encoding="utf-8",

        )



        (

            work

            /

            "VisualizerHarness.java"

        ).write_text(

            _harness_java(

                info,

                values,

            ),

            encoding="utf-8",

        )





        # ----------------------------------------------------

        # Compile instrumented version

        # ----------------------------------------------------



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

            return {

                "success":

                    False,



                "type":

                    "compile_timeout",



                "message":

                    "Compilation exceeded "

                    "the time limit.",

            }





        # ----------------------------------------------------

        # If instrumentation broke compilation, retry the exact

        # original Java source.

        # ----------------------------------------------------



        if (

            compiled.returncode

            !=

            0

        ):

            instrumentation_error = (

                compiled.stderr[

                    -MAX_OUTPUT:

                ]

            )



            student_path.write_text(

                source,

                encoding="utf-8",

            )



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

                return {

                    "success":

                        False,



                    "type":

                        "compile_timeout",



                    "message":

                        "Compilation exceeded "

                        "the time limit.",

                }





            # ------------------------------------------------

            # Original source also fails → real compile error

            # ------------------------------------------------



            if (

                retry.returncode

                !=

                0

            ):

                return {

                    "success":

                        False,



                    "type":

                        "compile_error",



                    "message":

                        (

                            retry.stderr[

                                -MAX_OUTPUT:

                            ]

                            or

                            retry.stdout[

                                -MAX_OUTPUT:

                            ]

                        ),

                }





            trace_expected = False



            trace_reason = (

                "The original Java code compiled and executed, "

                "but the instrumented tracing version did not "

                "compile.\n\n"

                "Instrumentation compiler error:\n"

                +

                instrumentation_error

            )





        # ----------------------------------------------------

        # Execute Java

        # ----------------------------------------------------



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

                "success":

                    False,



                "type":

                    "timeout",



                "message":

                    (

                        f"Execution exceeded "

                        f"{RUN_TIMEOUT} seconds "

                        f"(possible infinite loop "

                        f"or very slow code)."

                    ),

            }





        # ----------------------------------------------------

        # Extract final array + trace + stdout

        # ----------------------------------------------------



        (

            final,

            trace,

            user_stdout,

        ) = _extract_payload(

            ran.stdout

        )





        # ----------------------------------------------------

        # Runtime failure

        # ----------------------------------------------------



        if (

            ran.returncode

            !=

            0

        ):

            stderr = (

                ran.stderr[

                    -MAX_OUTPUT:

                ]

            )



            if (

                "__USER_EXCEPTION__"

                in stderr

            ):

                first = (

                    stderr.split(

                        "__USER_EXCEPTION__",

                        1,

                    )[1]

                )



                return {

                    "success":

                        False,



                    "type":

                        "runtime_error",



                    "message":

                        first,



                    "stdout":

                        user_stdout,



                    "trace":

                        trace[

                            :MAX_STEPS

                        ],

                }





            return {

                "success":

                    False,



                "type":

                    "runtime_error",



                "message":

                    (

                        stderr

                        or

                        (

                            "Java process exited "

                            "with a non-zero status."

                        )

                    ),



                "stdout":

                    user_stdout,



                "trace":

                    trace[

                        :MAX_STEPS

                    ],

            }





        # ----------------------------------------------------

        # Success

        # ----------------------------------------------------



        return {

            "success":

                True,



            "type":

                "success",



            "className":

                info.class_name,



            "methodName":

                info.method_name,



            "parameterKind":

                info.parameter_kind,



            "finalArray":

                final,



            "stdout":

                user_stdout,



            "stderr":

                ran.stderr[

                    -MAX_OUTPUT:

                ],



            "trace":

                trace[

                    :MAX_STEPS

                ],



            "traceAvailable":

                (

                    bool(trace)

                    and

                    trace_expected

                ),



            "traceNote":

                trace_reason,

        }
