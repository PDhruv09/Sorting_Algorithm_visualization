let executionSteps = [];
let currentStepIndex = 0;
let isPlaying = false;
let playInterval = null;

let animationSpeed = 500;

let codeLines = [];
let selectedAlgorithm = null;
let originalInputArray = [];


const $ = (id) => document.getElementById(id);


/* ============================================================
 * Page setup
 * ============================================================ */

window.addEventListener('load', () => {
    const speedSlider = $('speedSlider');

    if (speedSlider) {
        speedSlider.addEventListener(
            'input',
            () => {
                updateAnimationSpeed();

                if (isPlaying) {
                    stopPlayback();
                    pauseResume();
                }
            }
        );
    }

    updateAnimationSpeed();
    resetVisualization();
    loadStarterExample();
});


function updateAnimationSpeed() {
    const slider = $('speedSlider');

    if (!slider) {
        animationSpeed = 500;
        return;
    }

    const level = parseInt(
        slider.value,
        10
    );

    const delays = [
        2000,
        1600,
        1250,
        1000,
        750,
        500,
        350,
        250,
        150,
        75
    ];

    const normalizedLevel = Math.max(
        1,
        Math.min(
            10,
            Number.isFinite(level)
                ? level
                : 6
        )
    );

    animationSpeed =
        delays[
            normalizedLevel - 1
        ];

    let label;

    if (normalizedLevel <= 3) {
        label = 'Slow';
    } else if (normalizedLevel <= 7) {
        label = 'Normal';
    } else {
        label = 'Fast';
    }

    const speedValue = $('speedValue');

    if (speedValue) {
        speedValue.textContent =
            `${label} (${normalizedLevel}/10)`;
    }
}


/* ============================================================
 * Starter example
 * ============================================================ */

function loadStarterExample() {
    const editor = $('javaCode');

    if (!editor) {
        return;
    }

    if (editor.value.trim()) {
        return;
    }

    editor.value =
`public static void insertionSort(int[] arr) {
    for (int i = 1; i < arr.length; i++) {
        int key = arr[i];
        int j = i - 1;

        while (j >= 0 && arr[j] > key) {
            arr[j + 1] = arr[j];
            j--;
        }

        arr[j + 1] = key;
    }
}`;
}


/* ============================================================
 * Input parsing
 * ============================================================ */

function parseInputArray() {
    const raw =
        $('inputArray').value.trim();

    if (!raw) {
        throw new Error(
            'Input array cannot be empty.'
        );
    }

    const values = raw
        .split(',')
        .map(value => value.trim())
        .filter(Boolean)
        .map(value => Number(value));

    if (
        values.length === 0 ||
        values.some(
            value =>
                !Number.isInteger(value)
        )
    ) {
        throw new Error(
            'Input array must be comma-separated integers.'
        );
    }

    if (values.length > 500) {
        throw new Error(
            'Input array is limited to 500 integers.'
        );
    }

    return values;
}


/* ============================================================
 * API error handling
 * ============================================================ */

function formatApiError(
    detail,
    status
) {
    if (!detail) {
        return `HTTP ${status}`;
    }

    if (
        typeof detail ===
        'string'
    ) {
        return detail;
    }

    if (
        Array.isArray(detail)
    ) {
        return detail
            .map(item => {
                if (
                    typeof item ===
                    'string'
                ) {
                    return item;
                }

                if (
                    item &&
                    typeof item ===
                    'object'
                ) {
                    const location =
                        Array.isArray(
                            item.loc
                        )
                            ? item.loc
                                .filter(
                                    part =>
                                        part !==
                                        'body'
                                )
                                .join(
                                    ' → '
                                )
                            : '';

                    const message =
                        item.msg ||
                        item.message ||
                        JSON.stringify(
                            item
                        );

                    return location
                        ? `${location}: ${message}`
                        : message;
                }

                return String(item);
            })
            .join('\n');
    }

    if (
        typeof detail ===
        'object'
    ) {
        return (
            detail.message ||
            detail.msg ||
            JSON.stringify(
                detail
            )
        );
    }

    return String(detail);
}

function scrollToVisualization() {
    const panel =
        $('visualizationPanel');

    if (!panel) {
        return;
    }

    panel.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
    });
}

/* ============================================================
 * Execute submitted Java
 * ============================================================ */

async function executeCode() {
    clearError();
    clearInfo();
    stopPlayback();

    const code =
        $('javaCode').value;

    let inputArray;

    try {
        inputArray =
            parseInputArray();

        originalInputArray =
            [...inputArray];

    } catch (error) {
        showError(
            error.message
        );

        return;
    }

    if (!code.trim()) {
        showError(
            'Code cannot be empty.'
        );

        return;
    }

    selectedAlgorithm =
        detectAlgorithmFromCode(
            code
        );

    setResult(
        'Running javac and the actual Java method…',
        '',
        false
    );

    scrollToVisualization();

    const executeButton =
        document.querySelector(
            '.btn-primary'
        );

    if (executeButton) {
        executeButton.disabled = true;
    }

    try {
        const response =
            await fetch(
                '/api/execute',
                {
                    method: 'POST',

                    headers: {
                        'Content-Type':
                            'application/json'
                    },

                    body:
                        JSON.stringify(
                            {
                                code,

                                inputArray,

                                methodName:
                                    $('methodName')
                                        .value
                                        .trim() ||
                                    null
                            }
                        )
                }
            );

        let result;

        try {
            result =
                await response.json();

        } catch {
            throw new Error(
                `Server returned HTTP ${response.status} without valid JSON.`
            );
        }

        if (!response.ok) {
            throw new Error(
                formatApiError(
                    result.detail,
                    response.status
                )
            );
        }

        codeLines =
            code.split('\n');

        displayCode();

        analyzeComplexity(
            code
        );

        if (!result.success) {
            executionSteps =
                Array.isArray(
                    result.trace
                )
                    ? normalizeTrace(
                        result.trace,
                        inputArray
                    )
                    : [];

            currentStepIndex =
                Math.max(
                    0,
                    executionSteps.length -
                        1
                );

            if (
                executionSteps.length
            ) {
                visualizeStep(
                    currentStepIndex
                );
            } else {
                renderVisualization(
                    inputArray,
                    null
                );

                updateStatus();
            }

            const label =
                formatErrorType(
                    result.type
                );

            setResult(
                `${label}\n${result.message || 'Execution failed.'}`,
                result.stdout || '',
                true
            );

            showError(
                `${label}: ${firstLine(
                    result.message ||
                    'Execution failed.'
                )}`
            );

            return;
        }

        executionSteps =
            normalizeTrace(
                result.trace || [],
                inputArray
            );

        currentStepIndex = 0;

        updateStatus();

        if (
            executionSteps.length
        ) {
            visualizeStep(0);

        } else {
            renderVisualization(
                inputArray,
                null
            );
        }

        let message =
            `Compiled and executed successfully.\n` +
            `Class: ${result.className}\n` +
            `Method: ${result.methodName}`;

        if (
            selectedAlgorithm
        ) {
            message +=
                `\nDetected visualization mode: ` +
                `${formatAlgorithmName(
                    selectedAlgorithm
                )}`;
        }

        if (
            result.traceAvailable ===
            false
        ) {
            message +=
                `\n\nVisualization note: ` +
                `${
                    result.traceNote ||
                    'Intermediate tracing was unavailable, but the actual Java code still ran.'
                }`;

            showInfo(
                result.traceNote ||
                'Java executed successfully, but intermediate tracing was unavailable.'
            );
        }

        const output = [
            result.finalArray
                ? `Final array: ${result.finalArray}`
                : '',

            result.stdout
                ? `Program stdout:\n${result.stdout}`
                : '',

            result.stderr
                ? `Program stderr:\n${result.stderr}`
                : ''
        ]
            .filter(Boolean)
            .join('\n\n') || '-';

        setResult(
            message,
            output,
            false
        );

        if (
            executionSteps.length >
            1
        ) {
            pauseResume();
        }

    } catch (error) {
        setResult(
            'Runner error\n' +
                error.message,
            '',
            true
        );

        showError(
            error.message
        );

    } finally {
        if (executeButton) {
            executeButton.disabled =
                false;
        }
    }
}


/* ============================================================
 * Trace normalization
 * ============================================================ */

function normalizeTrace(
    trace,
    initial
) {
    if (
        !Array.isArray(trace)
    ) {
        return [];
    }

    const result =
        trace.filter(
            step =>
                step &&
                Array.isArray(
                    step.array
                )
        );

    if (
        result.length === 0
    ) {
        return [
            {
                type: 'start',

                data: {
                    indices: []
                },

                array:
                    [...initial],

                lineNum: 0,

                comparisons: 0,

                swaps: 0,

                arrayAccesses: 0
            }
        ];
    }

    return coalesceSwaps(
        result
    );
}


/*
 * Java swaps are usually implemented as several assignments.
 *
 * The backend traces literal assignments. This pass recognizes
 * pairs of writes that together form a conceptual swap so the
 * visualization can show one swap operation instead of two
 * unrelated writes.
 */
function coalesceSwaps(
    steps
) {
    const output = [];

    let i = 0;

    while (
        i < steps.length
    ) {
        const current =
            steps[i];

        const previous =
            output.length
                ? output[
                    output.length - 1
                ]
                : null;

        if (
            previous &&
            current.type ===
                'write' &&
            current.data &&
            Array.isArray(
                current.data.indices
            ) &&
            current.data.indices
                .length === 1
        ) {
            const firstIndex =
                current.data
                    .indices[0];

            let secondWritePosition =
                -1;

            for (
                let j = i + 1;
                j <
                    Math.min(
                        steps.length,
                        i + 5
                    );
                j++
            ) {
                const candidate =
                    steps[j];

                if (
                    candidate.type ===
                        'write' &&
                    candidate.data &&
                    Array.isArray(
                        candidate.data
                            .indices
                    ) &&
                    candidate.data
                        .indices
                        .length === 1
                ) {
                    secondWritePosition =
                        j;

                    break;
                }

                /*
                 * If the array changes for another reason
                 * before a second write, this is not a
                 * straightforward conceptual swap.
                 */
                if (
                    !arraysEqual(
                        candidate.array,
                        current.array
                    )
                ) {
                    break;
                }
            }

            if (
                secondWritePosition !==
                -1
            ) {
                const second =
                    steps[
                        secondWritePosition
                    ];

                const secondIndex =
                    second.data
                        .indices[0];

                if (
                    firstIndex !==
                        secondIndex &&
                    isExactSwap(
                        previous.array,
                        second.array,
                        firstIndex,
                        secondIndex
                    )
                ) {
                    output.push(
                        {
                            ...second,

                            type:
                                'swap',

                            data: {
                                indices: [
                                    firstIndex,
                                    secondIndex
                                ]
                            }
                        }
                    );

                    i =
                        secondWritePosition +
                        1;

                    continue;
                }
            }
        }

        output.push(
            current
        );

        i++;
    }

    /*
     * Recalculate the swap count using semantic swaps
     * recognized above.
     */
    let semanticSwapCount = 0;

    for (
        const step of output
    ) {
        if (
            step.type === 'swap'
        ) {
            semanticSwapCount++;
        }

        step.swaps =
            semanticSwapCount;
    }

    return output;
}


function arraysEqual(
    first,
    second
) {
    if (
        !Array.isArray(first) ||
        !Array.isArray(second)
    ) {
        return false;
    }

    if (
        first.length !==
        second.length
    ) {
        return false;
    }

    return first.every(
        (
            value,
            index
        ) =>
            value ===
            second[index]
    );
}


function isExactSwap(
    before,
    after,
    firstIndex,
    secondIndex
) {
    if (
        !Array.isArray(before) ||
        !Array.isArray(after) ||
        before.length !==
            after.length
    ) {
        return false;
    }

    if (
        before[firstIndex] !==
            after[secondIndex] ||
        before[secondIndex] !==
            after[firstIndex]
    ) {
        return false;
    }

    for (
        let index = 0;
        index < before.length;
        index++
    ) {
        if (
            index !== firstIndex &&
            index !== secondIndex &&
            before[index] !==
                after[index]
        ) {
            return false;
        }
    }

    return true;
}


/* ============================================================
 * Execution results
 * ============================================================ */

function formatErrorType(
    type
) {
    const names = {
        compile_error:
            'Compilation Error',

        compile_timeout:
            'Compilation Timeout',

        runtime_error:
            'Runtime Error',

        timeout:
            'Execution Timeout'
    };

    return (
        names[type] ||
        'Execution Error'
    );
}


function firstLine(value) {
    return String(value)
        .split('\n')[0];
}


function setResult(
    message,
    output,
    error
) {
    const messageElement =
        $('executionMessage');

    const outputElement =
        $('programOutput');

    if (messageElement) {
        messageElement.textContent =
            message || '-';

        messageElement
            .classList
            .toggle(
                'error',
                Boolean(error)
            );

        messageElement
            .classList
            .toggle(
                'success',
                !error &&
                message &&
                message !==
                    'Ready.'
            );
    }

    if (outputElement) {
        outputElement.textContent =
            output || '-';
    }
}


/* ============================================================
 * User notices
 * ============================================================ */

function showError(
    message
) {
    clearError();
    clearInfo();

    const errorDiv =
        document.createElement(
            'div'
        );

    errorDiv.className =
        'error-message';

    errorDiv.id =
        'error-display';

    errorDiv.textContent =
        message;

    const codeEditor =
        document.querySelector(
            '.code-editor'
        );

    if (codeEditor) {
        codeEditor.appendChild(
            errorDiv
        );
    }
}


function showInfo(
    message
) {
    clearInfo();

    const infoDiv =
        document.createElement(
            'div'
        );

    infoDiv.className =
        'info-message';

    infoDiv.id =
        'info-display';

    infoDiv.textContent =
        message;

    const codeEditor =
        document.querySelector(
            '.code-editor'
        );

    if (codeEditor) {
        codeEditor.appendChild(
            infoDiv
        );
    }
}


function clearError() {
    const element =
        $('error-display');

    if (element) {
        element.remove();
    }
}


function clearInfo() {
    const element =
        $('info-display');

    if (element) {
        element.remove();
    }
}


/* ============================================================
 * Source-code display
 * ============================================================ */

function displayCode() {
    const codeDisplay =
        $('codeDisplay');

    if (!codeDisplay) {
        return;
    }

    codeDisplay.innerHTML =
        '';

    codeLines.forEach(
        (
            line,
            index
        ) => {
            const lineDiv =
                document.createElement(
                    'div'
                );

            lineDiv.className =
                'code-line';

            lineDiv.innerHTML =
                `<span class="line-number">` +
                `${index + 1}</span>` +
                `${escapeHtml(line)}`;

            lineDiv.dataset.line =
                index;

            codeDisplay
                .appendChild(
                    lineDiv
                );
        }
    );
}


function escapeHtml(
    text
) {
    const div =
        document.createElement(
            'div'
        );

    div.textContent =
        text;

    return div.innerHTML;
}


/* ============================================================
 * Trace visualization
 * ============================================================ */

function visualizeStep(
    index
) {
    if (
        index < 0 ||
        index >=
            executionSteps.length
    ) {
        return;
    }

    currentStepIndex =
        index;

    const step =
        executionSteps[index];

    renderVisualization(
        step.array,
        step
    );

    document
        .querySelectorAll(
            '.code-line'
        )
        .forEach(
            line =>
                line.classList
                    .remove(
                        'executing'
                    )
        );

    const lineNum =
        Number.isInteger(
            step.lineNum
        )
            ? step.lineNum
            : -1;

    const currentLine =
        document.querySelector(
            `[data-line="${lineNum}"]`
        );

    if (currentLine) {
        currentLine.classList.add(
            'executing'
        );

        const codeDisplay =
            $('codeDisplay');

        if (codeDisplay) {
            const lineTop =
                currentLine.offsetTop;

            const lineHeight =
                currentLine.offsetHeight;

            const containerHeight =
                codeDisplay.clientHeight;

            const targetScroll =
                lineTop -
                containerHeight / 2 +
                lineHeight / 2;

            codeDisplay.scrollTo(
                {
                    top:
                        Math.max(
                            0,
                            targetScroll
                        ),

                    behavior:
                        'smooth'
                }
            );
        }
    }

    updateStatus();
}


/* ============================================================
 * Visualization routing
 * ============================================================ */

function renderVisualization(
    values,
    step
) {
    if (
        selectedAlgorithm ===
        'quick'
    ) {
        renderQuickVisualization(
            values,
            step
        );

        return;
    }

    if (
        selectedAlgorithm ===
        'counting'
    ) {
        renderCountingVisualization(
            values,
            step
        );

        return;
    }

    if (
        selectedAlgorithm ===
        'heap'
    ) {
        renderHeapVisualization(
            values,
            step
        );

        return;
    }

    if (
        selectedAlgorithm ===
        'bucket'
    ) {
        renderBucketVisualization(
            values,
            step
        );

        return;
    }

    renderArray(
        values,
        step
    );
}


/* ============================================================
 * Generic bar visualization
 * ============================================================ */

function buildBars(
    container,
    values,
    step,
    maxHeight = 300
) {
    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const maxAbs =
        Math.max(
            1,
            ...values.map(
                value =>
                    Math.abs(value)
            )
        );

    const arraySize =
        values.length;

    const containerWidth =
        Math.max(
            300,
            container.clientWidth -
                40
        );

    let barWidth =
        arraySize <= 20
            ? Math.floor(
                containerWidth /
                arraySize
            ) - 4
            : Math.max(
                10,
                Math.floor(
                    containerWidth /
                    arraySize
                ) - 3
            );

    barWidth =
        Math.max(
            8,
            barWidth
        );

    const changed =
        new Set(
            step &&
            step.data &&
            Array.isArray(
                step.data.indices
            )
                ? step.data.indices
                : []
        );

    values.forEach(
        (
            value,
            index
        ) => {
            const bar =
                document
                    .createElement(
                        'div'
                    );

            bar.className =
                'bar';

            const scaled =
                Math.max(
                    8,
                    Math.round(
                        (
                            Math.abs(
                                value
                            ) /
                            maxAbs
                        ) *
                        maxHeight
                    )
                );

            bar.style.height =
                scaled + 'px';

            bar.style.width =
                barWidth + 'px';

            bar.title =
                `Index ${index}: ${value}`;

            if (step) {
                if (
                    step.type ===
                        'condition' &&
                    changed.has(index)
                ) {
                    bar.classList.add(
                        'comparing'
                    );

                } else if (
                    step.type ===
                        'swap' &&
                    changed.has(index)
                ) {
                    bar.classList.add(
                        'swapping'
                    );

                } else if (
                    step.type ===
                        'write' &&
                    changed.has(index)
                ) {
                    bar.classList.add(
                        'writing'
                    );

                } else if (
                    step.type ===
                    'complete'
                ) {
                    bar.classList.add(
                        'sorted'
                    );
                }
            }

            const label =
                document
                    .createElement(
                        'span'
                    );

            label.className =
                'bar-value-label';

            label.textContent =
                value;

            bar.appendChild(
                label
            );

            container.appendChild(
                bar
            );
        }
    );
}


function renderArray(
    values,
    step
) {
    const visualArea =
        $('visualizationArea');

    if (!visualArea) {
        return;
    }

    visualArea.innerHTML =
        '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const bars =
        document.createElement(
            'div'
        );

    bars.className =
        'bars-stage';

    visualArea.appendChild(
        bars
    );

    buildBars(
        bars,
        values,
        step,
        300
    );
}


/* ============================================================
 * Quick Sort visualization
 * ============================================================ */

function renderQuickVisualization(
    values,
    step
) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML =
        '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const detail =
        document.createElement(
            'div'
        );

    detail.className =
        'algorithm-detail quick-detail';

    const line =
        step &&
        Number.isInteger(
            step.lineNum
        )
            ? (
                codeLines[
                    step.lineNum
                ] || ''
            ).trim()
            : '';

    let phase =
        'Partition / recursion';

    if (
        /pivot/i.test(line)
    ) {
        phase =
            'Pivot handling';

    } else if (
        step &&
        step.type ===
            'condition'
    ) {
        phase =
            'Partition comparison';

    } else if (
        step &&
        step.type ===
            'swap'
    ) {
        phase =
            'Partition swap';

    } else if (
        step &&
        step.type ===
            'method-entry'
    ) {
        phase =
            'Recursive/helper entry';

    } else if (
        step &&
        step.type ===
            'complete'
    ) {
        phase =
            'Quick Sort complete';
    }

    detail.innerHTML =
        `
        <div class="algorithm-detail-title">
            Quick Sort — Partition View
        </div>

        <div class="algorithm-detail-grid">
            <div>
                <span>Phase</span>
                <strong>
                    ${escapeHtml(phase)}
                </strong>
            </div>

            <div>
                <span>Current action</span>
                <strong>
                    ${escapeHtml(
                        describeStep(
                            step
                        )
                    )}
                </strong>
            </div>
        </div>

        <div class="algorithm-detail-note">
            The bars below come from the actual Java trace.
            Pivot/range details are shown only when they can
            be inferred safely from the executed source line.
        </div>
        `;

    if (line) {
        const sourceLine =
            document.createElement(
                'div'
            );

        sourceLine.className =
            'source-context';

        sourceLine.textContent =
            `Source: ${line}`;

        detail.appendChild(
            sourceLine
        );
    }

    visualArea.appendChild(
        detail
    );

    const bars =
        document.createElement(
            'div'
        );

    bars.className =
        'bars-stage compact-bars';

    visualArea.appendChild(
        bars
    );

    buildBars(
        bars,
        values,
        step,
        240
    );
}
/* ============================================================
 * Counting Sort visualization
 * ============================================================ */

function getCountingReference() {
    if (
        !originalInputArray.length
    ) {
        return null;
    }

    if (
        originalInputArray.some(
            value =>
                value < 0
        )
    ) {
        return null;
    }

    const max =
        Math.max(
            ...originalInputArray
        );

    if (max > 60) {
        return null;
    }

    const counts =
        new Array(
            max + 1
        ).fill(0);

    originalInputArray
        .forEach(
            value =>
                counts[value]++
        );

    return counts;
}


function renderCountingVisualization(
    values,
    step
) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML =
        '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const counts =
        getCountingReference();

    const detail =
        document.createElement(
            'div'
        );

    detail.className =
        'algorithm-detail counting-detail';

    const changed =
        step &&
        step.data &&
        Array.isArray(
            step.data.indices
        )
            ? step.data.indices
            : [];

    const currentValue =
        (
            step &&
            step.type ===
                'write' &&
            changed.length === 1 &&
            Number.isInteger(
                changed[0]
            )
        )
            ? values[
                changed[0]
            ]
            : null;

    detail.innerHTML =
        `
        <div class="algorithm-detail-title">
            Counting Sort — Frequency View
        </div>

        <div class="algorithm-detail-note">
            Frequency cells are derived from the original
            input as a reference. The main array below is
            always the actual Java execution trace.
        </div>
        `;

    if (counts) {
        const grid =
            document.createElement(
                'div'
            );

        grid.className =
            'count-grid';

        counts.forEach(
            (
                count,
                value
            ) => {
                const cell =
                    document
                        .createElement(
                            'div'
                        );

                cell.className =
                    'count-cell';

                if (
                    currentValue ===
                    value
                ) {
                    cell.classList.add(
                        'active'
                    );
                }

                cell.innerHTML =
                    `
                    <span class="count-value">
                        ${value}
                    </span>

                    <strong>
                        ${count}
                    </strong>
                    `;

                grid.appendChild(
                    cell
                );
            }
        );

        detail.appendChild(
            grid
        );

    } else {
        const note =
            document.createElement(
                'div'
            );

        note.className =
            'source-context';

        note.textContent =
            'Frequency reference is hidden for negative values or a very large value range.';

        detail.appendChild(
            note
        );
    }

    visualArea.appendChild(
        detail
    );

    const bars =
        document.createElement(
            'div'
        );

    bars.className =
        'bars-stage compact-bars';

    visualArea.appendChild(
        bars
    );

    buildBars(
        bars,
        values,
        step,
        220
    );
}


/* ============================================================
 * Bucket Sort visualization
 * ============================================================ */

function detectBucketCount(
    code
) {
    const match =
        String(code || '')
            .match(
                /\bbucketCount\s*=\s*(\d+)\s*;/
            );

    if (!match) {
        return null;
    }

    const count =
        Number(
            match[1]
        );

    if (
        !Number.isInteger(count) ||
        count < 1 ||
        count > 20
    ) {
        return null;
    }

    return count;
}


function getLiveBucketState(
    bucketCount
) {
    const buckets =
        Array.from(
            {
                length:
                    bucketCount
            },
            () => []
        );

    const end =
        Math.min(
            currentStepIndex,
            executionSteps.length - 1
        );

    for (
        let index = 0;
        index <= end;
        index++
    ) {
        const traceStep =
            executionSteps[index];

        if (
            !traceStep ||
            traceStep.type !==
                'bucket-write' ||
            !traceStep.data
        ) {
            continue;
        }

        const bucketIndex =
            traceStep.data
                .bucketIndex;

        const value =
            traceStep.data
                .value;

        if (
            Number.isInteger(
                bucketIndex
            ) &&
            bucketIndex >= 0 &&
            bucketIndex <
                buckets.length
        ) {
            buckets[
                bucketIndex
            ].push(
                value
            );
        }
    }

    return buckets;
}


function renderBucketVisualization(
    values,
    step
) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML =
        '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const code =
        $('javaCode').value;

    const bucketCount =
        detectBucketCount(
            code
        );

    const detail =
        document.createElement(
            'div'
        );

    detail.className =
        'algorithm-detail bucket-detail';

    detail.innerHTML =
        `
        <div class="algorithm-detail-title">
            Bucket Sort — Bucket View
        </div>

        <div class="algorithm-detail-grid">
            <div>
                <span>Phase</span>

                <strong>
                    ${
                        step &&
                        step.type ===
                            'bucket-write'
                            ? 'Distributing into buckets'
                            : step &&
                              step.type ===
                                'complete'
                                ? 'Bucket Sort complete'
                                : 'Executing Bucket Sort'
                    }
                </strong>
            </div>

            <div>
                <span>Current action</span>

                <strong>
                    ${escapeHtml(
                        describeStep(
                            step
                        )
                    )}
                </strong>
            </div>
        </div>

        <div class="algorithm-detail-note">
            Bucket contents below are filled from bucket-write
            events emitted by the actual Java execution.
        </div>
        `;


    if (bucketCount) {
        const buckets =
            getLiveBucketState(
                bucketCount
            );

        const activeBucket =
            (
                step &&
                step.type ===
                    'bucket-write' &&
                step.data
            )
                ? step.data
                    .bucketIndex
                : null;

        const bucketGrid =
            document.createElement(
                'div'
            );

        bucketGrid.className =
            'bucket-grid';


        buckets.forEach(
            (
                bucket,
                index
            ) => {
                const bucketElement =
                    document
                        .createElement(
                            'div'
                        );

                bucketElement.className =
                    'bucket-column';

                if (
                    index ===
                    activeBucket
                ) {
                    bucketElement
                        .classList
                        .add(
                            'active'
                        );
                }

                const title =
                    document
                        .createElement(
                            'span'
                        );

                title.className =
                    'bucket-title';

                title.textContent =
                    `Bucket ${index}`;

                bucketElement
                    .appendChild(
                        title
                    );


                const valuesWrap =
                    document
                        .createElement(
                            'div'
                        );

                valuesWrap.className =
                    'bucket-values';


                if (
                    bucket.length ===
                    0
                ) {
                    const empty =
                        document
                            .createElement(
                                'span'
                            );

                    empty.className =
                        'bucket-empty';

                    empty.textContent =
                        'empty';

                    valuesWrap
                        .appendChild(
                            empty
                        );

                } else {
                    bucket.forEach(
                        (
                            value,
                            valueIndex
                        ) => {
                            const chip =
                                document
                                    .createElement(
                                        'span'
                                    );

                            chip.className =
                                'bucket-chip';

                            chip.textContent =
                                value;

                            if (
                                index ===
                                    activeBucket &&
                                valueIndex ===
                                    bucket.length - 1
                            ) {
                                chip
                                    .classList
                                    .add(
                                        'active'
                                    );
                            }

                            valuesWrap
                                .appendChild(
                                    chip
                                );
                        }
                    );
                }


                bucketElement
                    .appendChild(
                        valuesWrap
                    );

                bucketGrid
                    .appendChild(
                        bucketElement
                    );
            }
        );


        detail.appendChild(
            bucketGrid
        );

    } else {
        const note =
            document.createElement(
                'div'
            );

        note.className =
            'source-context';

        note.textContent =
            'The bucket count could not be inferred safely, so only the actual array trace is shown.';

        detail.appendChild(
            note
        );
    }


    visualArea.appendChild(
        detail
    );


    const bars =
        document.createElement(
            'div'
        );

    bars.className =
        'bars-stage compact-bars';

    visualArea.appendChild(
        bars
    );


    buildBars(
        bars,
        values,
        step,
        210
    );
}
/* ============================================================
 * Heap Sort visualization
 * ============================================================ */

function getCurrentHeapSize(
    values,
    step
) {
    if (
        !values ||
        values.length === 0
    ) {
        return 0;
    }

    if (
        step &&
        step.type ===
            'complete'
    ) {
        return 0;
    }

    let heapSize =
        values.length;

    const end =
        Math.min(
            currentStepIndex,
            executionSteps.length - 1
        );

    for (
        let index = 0;
        index <= end;
        index++
    ) {
        const traceStep =
            executionSteps[index];

        if (
            traceStep &&
            traceStep.type ===
                'heap-boundary' &&
            traceStep.data &&
            Number.isInteger(
                traceStep.data.heapSize
            )
        ) {
            heapSize =
                traceStep.data
                    .heapSize;
        }
    }

    return Math.max(
        0,
        Math.min(
            heapSize,
            values.length
        )
    );
}


function renderHeapVisualization(
    values,
    step
) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML =
        '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const heapSize =
        getCurrentHeapSize(
            values,
            step
        );

    const changed =
        new Set(
            step &&
            step.data &&
            Array.isArray(
                step.data.indices
            )
                ? step.data.indices
                : []
        );

    let phase =
        'Array represented as a binary tree';

    if (
        step &&
        step.type ===
            'complete'
    ) {
        phase =
            'Heap Sort complete';

    } else if (
        heapSize <
        values.length
    ) {
        phase =
            'Extracting maximum / restoring heap';

    } else if (
        step &&
        (
            step.type ===
                'heap-boundary' ||
            step.type ===
                'method-entry'
        )
    ) {
        phase =
            'Building max heap';
    }

    const detail =
        document.createElement(
            'div'
        );

    detail.className =
        'algorithm-detail heap-detail';

    detail.innerHTML =
        `
        <div class="algorithm-detail-title">
            Heap Sort — Tree View
        </div>

        <div class="algorithm-detail-grid">
            <div>
                <span>Phase</span>
                <strong>
                    ${escapeHtml(phase)}
                </strong>
            </div>

            <div>
                <span>Active Heap</span>
                <strong>
                    ${heapSize}
                    ${
                        heapSize === 1
                            ? 'element'
                            : 'elements'
                    }
                </strong>
            </div>
        </div>

        <div class="algorithm-detail-note">
            The tree keeps the same array-index structure
            throughout Heap Sort. Values update in place as
            the Java array changes. Nodes outside the active
            heap are already in their final sorted positions.
        </div>
        `;

    visualArea.appendChild(
        detail
    );

    const treeSection =
        document.createElement(
            'div'
        );

    treeSection.className =
        'heap-section';

    const treeTitle =
        document.createElement(
            'div'
        );

    treeTitle.className =
        'heap-section-title';

    treeTitle.textContent =
        step &&
        step.type ===
            'complete'
            ? 'Final Sorted Tree'
            : 'Heap / Sorted Tree';

    treeSection.appendChild(
        treeTitle
    );

    const limit =
        Math.min(
            values.length,
            31
        );

    const shownValues =
        values.slice(
            0,
            limit
        );

    const levelCount =
        Math.floor(
            Math.log2(
                shownValues.length
            )
        ) + 1;

    const tree =
        document.createElement(
            'div'
        );

    tree.className =
        'heap-level-tree';

    const canvas =
        document.createElement(
            'div'
        );

    canvas.className =
        'heap-tree-canvas';

    canvas.style.height =
        `${Math.max(
            210,
            58 +
            levelCount * 76
        )}px`;

    const positions = [];

    shownValues.forEach(
        (
            value,
            index
        ) => {
            const level =
                Math.floor(
                    Math.log2(
                        index + 1
                    )
                );

            const firstIndex =
                Math.pow(
                    2,
                    level
                ) - 1;

            const positionInLevel =
                index -
                firstIndex;

            const nodesInLevel =
                Math.pow(
                    2,
                    level
                );

            const x =
                (
                    (
                        positionInLevel +
                        0.5
                    ) /
                    nodesInLevel
                ) * 100;

            const y =
                levelCount === 1
                    ? 50
                    : 13 +
                      level *
                      (
                          74 /
                          Math.max(
                              1,
                              levelCount - 1
                          )
                      );

            positions.push(
                {
                    index,
                    value,
                    x,
                    y
                }
            );
        }
    );

    const svg =
        document.createElementNS(
            'http://www.w3.org/2000/svg',
            'svg'
        );

    svg.classList.add(
        'heap-tree-svg'
    );

    svg.setAttribute(
        'viewBox',
        '0 0 100 100'
    );

    svg.setAttribute(
        'preserveAspectRatio',
        'none'
    );

    positions.forEach(
        position => {
            if (
                position.index === 0
            ) {
                return;
            }

            const parentIndex =
                Math.floor(
                    (
                        position.index -
                        1
                    ) / 2
                );

            const parent =
                positions[
                    parentIndex
                ];

            if (!parent) {
                return;
            }

            const line =
                document.createElementNS(
                    'http://www.w3.org/2000/svg',
                    'line'
                );

            line.setAttribute(
                'x1',
                parent.x
            );

            line.setAttribute(
                'y1',
                parent.y
            );

            line.setAttribute(
                'x2',
                position.x
            );

            line.setAttribute(
                'y2',
                position.y
            );

            line.classList.add(
                'heap-tree-line'
            );

            if (
                position.index >=
                heapSize
            ) {
                line.classList.add(
                    'sorted'
                );
            }

            svg.appendChild(
                line
            );
        }
    );

    canvas.appendChild(
        svg
    );

    positions.forEach(
        position => {
            const node =
                document.createElement(
                    'div'
                );

            node.className =
                'heap-node';

            node.style.left =
                `${position.x}%`;

            node.style.top =
                `${position.y}%`;

            node.innerHTML =
                `
                <span class="heap-node-value">
                    ${position.value}
                </span>

                <span class="heap-node-index">
                    [${position.index}]
                </span>
                `;

            const isSorted =
                (
                    step &&
                    step.type ===
                        'complete'
                ) ||
                position.index >=
                    heapSize;

            if (isSorted) {
                node.classList.add(
                    'sorted'
                );

            } else if (
                changed.has(
                    position.index
                )
            ) {
                if (
                    step &&
                    step.type ===
                        'condition'
                ) {
                    node.classList.add(
                        'comparing'
                    );

                } else if (
                    step &&
                    step.type ===
                        'swap'
                ) {
                    node.classList.add(
                        'swapping'
                    );

                } else if (
                    step &&
                    step.type ===
                        'write'
                ) {
                    node.classList.add(
                        'writing'
                    );
                }
            }

            canvas.appendChild(
                node
            );
        }
    );

    tree.appendChild(
        canvas
    );

    if (
        values.length >
        limit
    ) {
        const note =
            document.createElement(
                'div'
            );

        note.className =
            'heap-tree-limit';

        note.textContent =
            `Tree view limited to the first ${limit} array elements.`;

        tree.appendChild(
            note
        );
    }

    treeSection.appendChild(
        tree
    );

    visualArea.appendChild(
        treeSection
    );
}


/* ============================================================
 * Execution statistics
 * ============================================================ */

function updateStatus() {
    if (
        !executionSteps.length
    ) {
        $('currentAction')
            .textContent = '-';

        $('currentStep')
            .textContent = '0';

        $('totalSteps')
            .textContent = '0';

        $('comparisons')
            .textContent = '0';

        $('swaps')
            .textContent = '0';

        $('arrayAccesses')
            .textContent = '0';

        return;
    }

    const step =
        executionSteps[
            currentStepIndex
        ];

    $('currentAction')
        .textContent =
        describeStep(step);

    $('currentStep')
        .textContent =
        currentStepIndex + 1;

    $('totalSteps')
        .textContent =
        executionSteps.length;

    $('comparisons')
        .textContent =
        step.comparisons ?? 0;

    $('swaps')
        .textContent =
        step.swaps ?? 0;

    $('arrayAccesses')
        .textContent =
        step.arrayAccesses ?? 0;
}


function describeStep(
    step
) {
    if (!step) {
        return '-';
    }

    const indices =
        step.data &&
        Array.isArray(
            step.data.indices
        )
            ? step.data.indices
            : [];

    switch (
        step.type
    ) {
        case 'condition':
            return indices.length
                ? `Comparing index ${indices.join(' and ')}`
                : 'Comparing';

        case 'write':
            return indices.length
                ? `Writing / shifting index ${indices.join(', ')}`
                : 'Writing / shifting';

        case 'swap':
            return (
                indices.length ===
                2
            )
                ? `Swapping index ${indices[0]} ↔ ${indices[1]}`
                : 'Swapping';

        case 'complete':
            return 'Sorting complete';

        case 'method-entry':
            return 'Starting method';

        case 'start':
            return 'Initial array';

        case 'statement':
            return 'Executing statement';

        case 'bucket-write':
            if (
                step.data &&
                Number.isInteger(
                    step.data.bucketIndex
                )
            ) {
                return (
                    `Placing ${step.data.value} ` +
                    `into bucket ${step.data.bucketIndex}`
                );
            }

            return 'Placing value into bucket';

        case 'heap-boundary':
            if (
                step.data &&
                Number.isInteger(
                    step.data.heapSize
                )
            ) {
                return (
                    `Active heap size: ` +
                    `${step.data.heapSize}`
                );
            }

            return 'Updating active heap';

        default:
            return 'Executing';
    }
}
/* ============================================================
 * Step controls
 * ============================================================ */

function stepForward() {
    if (
        currentStepIndex <
        executionSteps.length -
            1
    ) {
        visualizeStep(
            currentStepIndex +
                1
        );
    }
}


function stepBackward() {
    if (
        currentStepIndex > 0
    ) {
        visualizeStep(
            currentStepIndex -
                1
        );
    }
}


/* ============================================================
 * Playback
 * ============================================================ */

function getPlayButton() {
    return [
        ...document
            .querySelectorAll(
                'button'
            )
    ].find(
        button =>
            button.getAttribute(
                'onclick'
            ) ===
            'pauseResume()'
    );
}


function stopPlayback() {
    isPlaying = false;

    if (playInterval) {
        clearInterval(
            playInterval
        );
    }

    playInterval = null;

    const button =
        getPlayButton();

    if (button) {
        button.textContent =
            '▶ Play';
    }
}


function pauseResume() {
    const button =
        getPlayButton();

    if (
        !executionSteps.length
    ) {
        return;
    }

    if (isPlaying) {
        stopPlayback();
        return;
    }

    if (
        currentStepIndex >=
        executionSteps.length - 1
    ) {
        currentStepIndex = 0;

        visualizeStep(0);
    }

    isPlaying = true;

    if (button) {
        button.textContent =
            '⏸ Pause';
    }

    playInterval =
        setInterval(
            () => {
                if (
                    currentStepIndex <
                    executionSteps.length -
                        1
                ) {
                    stepForward();

                } else {
                    stopPlayback();
                }
            },

            animationSpeed
        );
}


/* ============================================================
 * Reset
 * ============================================================ */

function resetVisualization() {
    stopPlayback();

    currentStepIndex = 0;
    executionSteps = [];

    selectedAlgorithm = null;
    originalInputArray = [];

    const visualArea =
        $('visualizationArea');

    if (visualArea) {
        visualArea.innerHTML =
            '';
    }

    const codeDisplay =
        $('codeDisplay');

    if (codeDisplay) {
        codeDisplay.innerHTML =
            '';
    }

    updateStatus();

    if (
        $('timeComplexity')
    ) {
        $('timeComplexity')
            .textContent = '-';
    }

    if (
        $('spaceComplexity')
    ) {
        $('spaceComplexity')
            .textContent = '-';
    }

    if (
        $('executionMessage')
    ) {
        setResult(
            'Ready.',
            '-',
            false
        );
    }

    clearError();
    clearInfo();
}


/* ============================================================
 * Automatic visualization-mode detection
 * ============================================================ */

function detectAlgorithmFromCode(
    code
) {
    const source =
        String(
            code || ''
        );

    const normalized =
        source.toLowerCase();

    if (
        /\bheapsort\b/i
            .test(source) ||
        /\bheap\s*sort\b/i
            .test(source) ||
        /\bheapify\b/i
            .test(source) ||
        /\bsiftdown\b/i
            .test(source) ||
        /\bsift_down\b/i
            .test(source) ||
        /\bsiftDown\b/
            .test(source)
    ) {
        return 'heap';
    }

    if (
        /\bcountingsort\b/i
            .test(source) ||
        /\bcounting\s*sort\b/i
            .test(source) ||
        (
            /\bcounts?\s*\[/
                .test(
                    normalized
                ) &&
            /new\s+int\s*\[/
                .test(
                    normalized
                )
        )
    ) {
        return 'counting';
    }

    if (
        /\bbucketsort\b/i
            .test(source) ||
        /\bbucket\s*sort\b/i
            .test(source) ||
        /\bbucketcount\b/i
            .test(source) ||
        /\bbuckets\b/i
            .test(source)
    ) {
        return 'bucket';
    }

    if (
        /\bquicksort\b/i
            .test(source) ||
        /\bquick\s*sort\b/i
            .test(source) ||
        /\bpartition\s*\(/
            .test(source) ||
        /\bpivot\b/i
            .test(source)
    ) {
        return 'quick';
    }

    if (
        /\bmergesort\b/i
            .test(source) ||
        /\bmerge\s*sort\b/i
            .test(source) ||
        (
            /\bmerge\s*\(/
                .test(source) &&
            /\bmid\b/i
                .test(source)
        )
    ) {
        return 'merge';
    }

    if (
        /\binsertionsort\b/i
            .test(source) ||
        /\binsertion\s*sort\b/i
            .test(source) ||
        (
            /\bkey\b/i
                .test(source) &&
            /\bj\s*--/
                .test(source)
        )
    ) {
        return 'insertion';
    }

    if (
        /\bselectionsort\b/i
            .test(source) ||
        /\bselection\s*sort\b/i
            .test(source) ||
        /\bminindex\b/i
            .test(source) ||
        /\bmin_idx\b/i
            .test(source) ||
        /\bminIndex\b/
            .test(source)
    ) {
        return 'selection';
    }

    if (
        /\bbubblesort\b/i
            .test(source) ||
        /\bbubble\s*sort\b/i
            .test(source) ||
        (
            /\bswapped\b/i
                .test(source) &&
            /\[\s*\w+\s*\+\s*1\s*\]/
                .test(source)
        )
    ) {
        return 'bubble';
    }

    return null;
}


function formatAlgorithmName(
    algorithm
) {
    const names = {
        bubble:
            'Bubble Sort',

        selection:
            'Selection Sort',

        insertion:
            'Insertion Sort',

        merge:
            'Merge Sort',

        quick:
            'Quick Sort',

        heap:
            'Heap Sort',

        counting:
            'Counting Sort',

        bucket:
            'Bucket Sort'
    };

    return (
        names[algorithm] ||
        'Generic array trace'
    );
}
/* ============================================================
 * Complexity estimation
 * ============================================================ */

function analyzeComplexity(
    code
) {
    let time =
        'Unknown';

    let space =
        'Unknown';

    const known = {
        bubble: {
            time:
                'O(n²)',

            space:
                'O(1)'
        },

        selection: {
            time:
                'O(n²)',

            space:
                'O(1)'
        },

        insertion: {
            time:
                'O(n²)',

            space:
                'O(1)'
        },

        merge: {
            time:
                'O(n log n)',

            space:
                'O(n)'
        },

        quick: {
            time:
                'O(n log n) average',

            space:
                'O(log n) average'
        },

        heap: {
            time:
                'O(n log n)',

            space:
                'O(1)'
        },

        counting: {
            time:
                'O(n + k)',

            space:
                'O(k)'
        },

        bucket: {
            time:
                'O(n + k) average',

            space:
                'O(n + k)'
        }
    };

    if (
        selectedAlgorithm &&
        known[
            selectedAlgorithm
        ]
    ) {
        time =
            known[
                selectedAlgorithm
            ].time;

        space =
            known[
                selectedAlgorithm
            ].space;

    } else {
        const hasRecursion =
            detectRecursion(
                code
            );

        const hasAux =
            /new\s+(?:int|Integer|Object)\s*\[/
                .test(code) ||
            /new\s+ArrayList/
                .test(code);

        const maxDepth =
            approximateLoopDepth(
                code
            );

        if (
            hasRecursion &&
            /\bpivot\b/i
                .test(code)
        ) {
            time =
                'O(n log n) average';

            space =
                hasAux
                    ? 'O(n)'
                    : 'O(log n) average';

        } else if (
            hasRecursion &&
            /(mid|\/\s*2|>>>\s*1)/
                .test(code)
        ) {
            time =
                'O(n log n)';

            space =
                hasAux
                    ? 'O(n)'
                    : 'O(log n)';

        } else if (
            hasRecursion
        ) {
            time =
                'Recursive / input-dependent';

            space =
                hasAux
                    ? 'O(n)'
                    : 'O(log n)–O(n)';

        } else if (
            maxDepth >= 3
        ) {
            time =
                'O(n³) pattern';

            space =
                hasAux
                    ? 'O(n) pattern'
                    : 'O(1) pattern';

        } else if (
            maxDepth === 2
        ) {
            time =
                'O(n²) pattern';

            space =
                hasAux
                    ? 'O(n) pattern'
                    : 'O(1) pattern';

        } else if (
            maxDepth === 1
        ) {
            time =
                'O(n) pattern';

            space =
                hasAux
                    ? 'O(n) pattern'
                    : 'O(1) pattern';

        } else {
            time =
                'O(1) pattern';

            space =
                hasAux
                    ? 'O(n) pattern'
                    : 'O(1) pattern';
        }
    }

    $('timeComplexity')
        .textContent =
        time;

    $('spaceComplexity')
        .textContent =
        space;
}


/* ============================================================
 * Basic recursion detection
 * ============================================================ */

function detectRecursion(
    code
) {
    const methodPattern =
        /(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:void|int|long|double|float|boolean|int\s*\[\]|ArrayList\s*<[^>]+>)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{/g;

    const methods =
        [
            ...code.matchAll(
                methodPattern
            )
        ].map(
            match =>
                match[1]
        );

    return methods.some(
        name => {
            const declarationPattern =
                new RegExp(
                    `(?:public\\s+|private\\s+|protected\\s+)?(?:static\\s+)?(?:void|int|long|double|float|boolean|int\\s*\\[\\]|ArrayList\\s*<[^>]+>)\\s+${escapeRegExp(
                        name
                    )}\\s*\\([^)]*\\)\\s*\\{`
                );

            const withoutDeclaration =
                code.replace(
                    declarationPattern,
                    ''
                );

            const callPattern =
                new RegExp(
                    `\\b${escapeRegExp(
                        name
                    )}\\s*\\(`
                );

            return callPattern
                .test(
                    withoutDeclaration
                );
        }
    );
}


function escapeRegExp(
    value
) {
    return String(value)
        .replace(
            /[.*+?^${}()|[\]\\]/g,
            '\\$&'
        );
}


/* ============================================================
 * Approximate nested-loop depth
 * ============================================================ */

function approximateLoopDepth(
    code
) {
    let depth = 0;
    let max = 0;

    const tokens =
        code.split(
            /(?=[{}])|(?<=[{}])/
        );

    const stack = [];

    for (
        const token
        of tokens
    ) {
        if (
            token.includes('{')
        ) {
            const before =
                token
                    .split('{')[0];

            const isLoop =
                /\b(for|while)\s*\(/
                    .test(
                        before
                    );

            stack.push(
                isLoop
            );

            if (isLoop) {
                depth++;

                max =
                    Math.max(
                        max,
                        depth
                    );
            }

        } else if (
            token.includes('}')
        ) {
            const wasLoop =
                stack.pop();

            if (wasLoop) {
                depth =
                    Math.max(
                        0,
                        depth - 1
                    );
            }
        }
    }

    if (max === 0) {    
        const loops =
            (
                code.match(
                    /\b(?:for|while)\s*\(/g
                ) || []
            ).length;

        max =
            Math.min(
                loops,
                3
            );
    }

    return max;
}
