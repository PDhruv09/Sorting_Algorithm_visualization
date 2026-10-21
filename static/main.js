let executionSteps = [];
let currentStepIndex = 0;
let isPlaying = false;
let playInterval = null;
let animationSpeed = 500;
let codeLines = [];
let selectedAlgorithm = null;
let originalInputArray = [];

const $ = (id) => document.getElementById(id);

window.addEventListener('load', () => {
    $('speedSlider').addEventListener('input', (e) => {
        animationSpeed = parseInt(e.target.value, 10);
        $('speedValue').textContent = animationSpeed + 'ms';

        if (isPlaying) {
            pauseResume();
            pauseResume();
        }
    });

    resetVisualization();
    loadStarterExample();
});


function loadStarterExample() {
    if ($('javaCode').value.trim()) return;

    $('javaCode').value = `public static void insertionSort(int[] arr) {
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


function parseInputArray() {
    const raw = $('inputArray').value.trim();

    if (!raw) {
        throw new Error('Input array cannot be empty.');
    }

    const values = raw
        .split(',')
        .map(x => x.trim())
        .filter(Boolean)
        .map(x => Number(x));

    if (
        values.length === 0 ||
        values.some(x => !Number.isInteger(x))
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


async function executeCode() {
    clearError();
    clearInfo();
    stopPlayback();

    const code = $('javaCode').value;

    let inputArray;

    try {
        inputArray = parseInputArray();
        originalInputArray = [...inputArray];
    } catch (e) {
        showError(e.message);
        return;
    }

    if (!code.trim()) {
        showError('Code cannot be empty.');
        return;
    }

    setResult(
        'Running javac and the actual Java method…',
        '',
        false
    );

    document.querySelector('.btn-primary').disabled = true;

    try {
        const response = await fetch('/api/execute', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                code,
                inputArray,
                methodName:
                    $('methodName').value.trim() || null
            })
        });

        let result;

        try {
            result = await response.json();
        } catch {
            throw new Error(
                `Server returned HTTP ${response.status} without valid JSON.`
            );
        }

        if (!response.ok) {
            throw new Error(
                result.detail || `HTTP ${response.status}`
            );
        }

        codeLines = code.split('\n');

        displayCode();
        analyzeComplexity(code);

        if (!result.success) {
            executionSteps =
                Array.isArray(result.trace)
                    ? result.trace
                    : [];

            currentStepIndex = Math.max(
                0,
                executionSteps.length - 1
            );

            if (executionSteps.length) {
                visualizeStep(currentStepIndex);
            }

            const label = formatErrorType(result.type);

            setResult(
                `${label}\n${result.message || 'Execution failed.'}`,
                result.stdout || '',
                true
            );

            showError(
                `${label}: ${firstLine(
                    result.message || 'Execution failed.'
                )}`
            );

            return;
        }

        executionSteps = normalizeTrace(
            result.trace || [],
            inputArray
        );

        currentStepIndex = 0;

        updateStatus();

        if (executionSteps.length) {
            visualizeStep(0);
        } else {
            renderVisualization(inputArray, null);
        }

        let message =
            `Compiled and executed successfully.\n` +
            `Class: ${result.className}\n` +
            `Method: ${result.methodName}`;

        if (result.traceAvailable === false) {
            message +=
                `\n\nVisualization note: ` +
                `${result.traceNote ||
                'Intermediate tracing was unavailable, but the actual Java code still ran.'}`;

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

        if (executionSteps.length > 1) {
            pauseResume();
        }

    } catch (error) {
        setResult(
            'Runner error\n' + error.message,
            '',
            true
        );

        showError(error.message);

    } finally {
        document.querySelector(
            '.btn-primary'
        ).disabled = false;
    }
}


function normalizeTrace(trace, initial) {
    if (!Array.isArray(trace)) {
        return [];
    }

    const result = trace.filter(
        step =>
            step &&
            Array.isArray(step.array)
    );

    if (result.length === 0) {
        return [{
            type: 'start',
            data: {
                indices: []
            },
            array: [...initial],
            lineNum: 0,
            comparisons: 0,
            swaps: 0,
            arrayAccesses: 0
        }];
    }

    return coalesceSwaps(result);
}


function coalesceSwaps(steps) {
    const output = [];

    let i = 0;

    while (i < steps.length) {
        const current = steps[i];

        const previous =
            output.length
                ? output[output.length - 1]
                : null;

        if (
            previous &&
            current.type === 'write' &&
            current.data &&
            Array.isArray(
                current.data.indices
            ) &&
            current.data.indices.length === 1
        ) {
            const firstIndex =
                current.data.indices[0];

            let secondWritePosition = -1;

            for (
                let j = i + 1;
                j < Math.min(
                    steps.length,
                    i + 5
                );
                j++
            ) {
                const candidate = steps[j];

                if (
                    candidate.type === 'write' &&
                    candidate.data &&
                    Array.isArray(
                        candidate.data.indices
                    ) &&
                    candidate.data.indices.length === 1
                ) {
                    secondWritePosition = j;
                    break;
                }

                /*
                 * If the array changes for some other
                 * reason before the second write,
                 * this is not a simple swap.
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
                secondWritePosition !== -1
            ) {
                const second =
                    steps[secondWritePosition];

                const secondIndex =
                    second.data.indices[0];

                if (
                    firstIndex !== secondIndex &&
                    isExactSwap(
                        previous.array,
                        second.array,
                        firstIndex,
                        secondIndex
                    )
                ) {
                    output.push({
                        ...second,

                        type: 'swap',

                        data: {
                            indices: [
                                firstIndex,
                                secondIndex
                            ]
                        }
                    });

                    /*
                     * Skip the two individual
                     * assignment/write states and
                     * display one conceptual swap.
                     */
                    i =
                        secondWritePosition + 1;

                    continue;
                }
            }
        }

        output.push(current);

        i++;
    }

    /*
     * The backend records literal Java assignments.
     * Now that the frontend has recognized conceptual
     * swaps, recalculate swaps as a cumulative
     * semantic count.
     */
    let semanticSwapCount = 0;

    for (const step of output) {
        if (step.type === 'swap') {
            semanticSwapCount++;
        }

        step.swaps =
            semanticSwapCount;
    }

    return output;
}


function arraysEqual(a, b) {
    if (
        !Array.isArray(a) ||
        !Array.isArray(b)
    ) {
        return false;
    }

    if (a.length !== b.length) {
        return false;
    }

    return a.every(
        (value, index) =>
            value === b[index]
    );
}


function isExactSwap(
    before,
    after,
    i,
    j
) {
    if (
        !Array.isArray(before) ||
        !Array.isArray(after) ||
        before.length !== after.length
    ) {
        return false;
    }

    /*
     * The values at i and j must have
     * exchanged positions.
     */
    if (
        before[i] !== after[j] ||
        before[j] !== after[i]
    ) {
        return false;
    }

    /*
     * Every other location must remain
     * unchanged.
     */
    for (
        let k = 0;
        k < before.length;
        k++
    ) {
        if (
            k !== i &&
            k !== j &&
            before[k] !== after[k]
        ) {
            return false;
        }
    }

    return true;
}


function formatErrorType(type) {
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

    return names[type] ||
        'Execution Error';
}


function firstLine(s) {
    return String(s)
        .split('\n')[0];
}


function setResult(
    message,
    output,
    error
) {
    const msg =
        $('executionMessage');

    const out =
        $('programOutput');

    msg.textContent =
        message || '-';

    out.textContent =
        output || '-';

    msg.classList.toggle(
        'error',
        !!error
    );

    msg.classList.toggle(
        'success',
        !error &&
        message &&
        message !== 'Ready.'
    );
}


function showError(message) {
    clearError();
    clearInfo();

    const errorDiv =
        document.createElement('div');

    errorDiv.className =
        'error-message';

    errorDiv.id =
        'error-display';

    errorDiv.textContent =
        message;

    document
        .querySelector('.code-editor')
        .appendChild(errorDiv);
}


function showInfo(message) {
    clearInfo();

    const infoDiv =
        document.createElement('div');

    infoDiv.className =
        'info-message';

    infoDiv.id =
        'info-display';

    infoDiv.textContent =
        message;

    document
        .querySelector('.code-editor')
        .appendChild(infoDiv);
}


function clearError() {
    const el =
        $('error-display');

    if (el) {
        el.remove();
    }
}


function clearInfo() {
    const el =
        $('info-display');

    if (el) {
        el.remove();
    }
}


function displayCode() {
    const codeDisplay =
        $('codeDisplay');

    codeDisplay.innerHTML = '';

    codeLines.forEach(
        (line, index) => {
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

            codeDisplay.appendChild(
                lineDiv
            );
        }
    );
}


function escapeHtml(text) {
    const div =
        document.createElement('div');

    div.textContent = text;

    return div.innerHTML;
}


function visualizeStep(index) {
    if (
        index < 0 ||
        index >= executionSteps.length
    ) {
        return;
    }

    currentStepIndex = index;

    const step =
        executionSteps[index];

    renderVisualization(
        step.array,
        step
    );

    document
        .querySelectorAll('.code-line')
        .forEach(
            line =>
                line.classList.remove(
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

        codeDisplay.scrollTo({
            top: Math.max(0, targetScroll),
            behavior: 'smooth'
        });
    }

    updateStatus();
}


function renderVisualization(values, step) {
    if (selectedAlgorithm === 'quick') {
        renderQuickVisualization(values, step);
        return;
    }

    if (selectedAlgorithm === 'counting') {
        renderCountingVisualization(values, step);
        return;
    }

    if (selectedAlgorithm === 'bucket') {
        renderBucketVisualization(values, step);
        return;
    }

    renderArray(values, step);
}


function buildBars(container, values, step, maxHeight = 300) {
    if (!values || values.length === 0) return;

    const maxAbs = Math.max(
        1,
        ...values.map(v => Math.abs(v))
    );

    const arraySize = values.length;
    const containerWidth = Math.max(
        300,
        container.clientWidth - 40
    );

    let barWidth = arraySize <= 20
        ? Math.floor(containerWidth / arraySize) - 4
        : Math.max(
            10,
            Math.floor(containerWidth / arraySize) - 3
        );

    barWidth = Math.max(
        8,
        barWidth
    );

    const changed = new Set(
        step &&
        step.data &&
        Array.isArray(step.data.indices)
            ? step.data.indices
            : []
    );

    values.forEach((value, idx) => {
        const bar =
            document.createElement('div');

        bar.className = 'bar';

        const scaled =
            Math.max(
                8,
                Math.round(
                    (
                        Math.abs(value) /
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
            `Index ${idx}: ${value}`;

        if (step) {
            if (
                step.type === 'condition' &&
                changed.has(idx)
            ) {
                bar.classList.add(
                    'comparing'
                );

            } else if (
                step.type === 'swap' &&
                changed.has(idx)
            ) {
                bar.classList.add(
                    'swapping'
                );

            } else if (
                step.type === 'write' &&
                changed.has(idx)
            ) {
                bar.classList.add(
                    'writing'
                );

            } else if (
                step.type === 'complete'
            ) {
                bar.classList.add(
                    'sorted'
                );
            }
        }

        const label =
            document.createElement('span');

        label.className =
            'bar-value-label';

        label.textContent =
            value;

        bar.appendChild(label);

        container.appendChild(bar);
    });
}


function renderArray(values, step) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML = '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const bars =
        document.createElement('div');

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


function renderQuickVisualization(values, step) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML = '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const detail =
        document.createElement('div');

    detail.className =
        'algorithm-detail quick-detail';

    const line =
        step &&
        Number.isInteger(step.lineNum)
            ? (
                codeLines[
                    step.lineNum
                ] || ''
            ).trim()
            : '';

    let phase =
        'Partition / recursion';

    if (/pivot/i.test(line)) {
        phase =
            'Pivot handling';

    } else if (
        step &&
        step.type === 'condition'
    ) {
        phase =
            'Partition comparison';

    } else if (
        step &&
        step.type === 'swap'
    ) {
        phase =
            'Partition swap';

    } else if (
        step &&
        step.type === 'method-entry'
    ) {
        phase =
            'Recursive/helper entry';

    } else if (
        step &&
        step.type === 'complete'
    ) {
        phase =
            'Quick Sort complete';
    }

    detail.innerHTML = `
        <div class="algorithm-detail-title">
            Quick Sort — Partition View
        </div>

        <div class="algorithm-detail-grid">
            <div>
                <span>Phase</span>
                <strong>${escapeHtml(phase)}</strong>
            </div>

            <div>
                <span>Current action</span>
                <strong>${escapeHtml(
                    describeStep(step)
                )}</strong>
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
            document.createElement('div');

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
        document.createElement('div');

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


function getCountingReference() {
    if (!originalInputArray.length) {
        return null;
    }

    if (
        originalInputArray.some(
            v => v < 0
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
        new Array(max + 1)
            .fill(0);

    originalInputArray.forEach(
        v => counts[v]++
    );

    return counts;
}


function renderCountingVisualization(
    values,
    step
) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML = '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const counts =
        getCountingReference();

    const detail =
        document.createElement('div');

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
            step.type === 'write' &&
            changed.length === 1 &&
            Number.isInteger(
                changed[0]
            )
        )
            ? values[
                changed[0]
            ]
            : null;

    detail.innerHTML = `
        <div class="algorithm-detail-title">
            Counting Sort — Frequency View
        </div>

        <div class="algorithm-detail-note">
            Frequency cells are derived from the
            original input as a reference.
            The main array below is always the
            actual Java execution trace.
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
            (count, value) => {
                const cell =
                    document.createElement(
                        'div'
                    );

                cell.className =
                    'count-cell';

                if (
                    currentValue === value
                ) {
                    cell.classList.add(
                        'active'
                    );
                }

                cell.innerHTML = `
                    <span class="count-value">
                        ${value}
                    </span>
                    <strong>${count}</strong>
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


function detectBucketReference(code) {
    const countMatch =
        code.match(
            /\bbucketCount\s*=\s*(\d+)\s*;/
        );

    if (
        !countMatch ||
        !originalInputArray.length
    ) {
        return null;
    }

    const bucketCount =
        Number(
            countMatch[1]
        );

    if (
        !Number.isInteger(
            bucketCount
        ) ||
        bucketCount < 1 ||
        bucketCount > 20
    ) {
        return null;
    }

    const standardFormula =
        /\(\s*\w+\s*\*\s*bucketCount\s*\)\s*\/\s*\(\s*max\s*\+\s*1\s*\)/.test(
            code
        );

    if (!standardFormula) {
        return null;
    }

    const max =
        Math.max(
            ...originalInputArray
        );

    if (max < 0) {
        return null;
    }

    const buckets =
        Array.from(
            {
                length:
                    bucketCount
            },
            () => []
        );

    for (
        const value
        of originalInputArray
    ) {
        const index =
            Math.floor(
                (
                    value *
                    bucketCount
                ) /
                (max + 1)
            );

        if (
            index < 0 ||
            index >= bucketCount
        ) {
            return null;
        }

        buckets[index].push(
            value
        );
    }

    return buckets;
}


function renderBucketVisualization(
    values,
    step
) {
    const visualArea =
        $('visualizationArea');

    visualArea.innerHTML = '';

    if (
        !values ||
        values.length === 0
    ) {
        return;
    }

    const code =
        $('javaCode').value;

    const buckets =
        detectBucketReference(
            code
        );

    const detail =
        document.createElement('div');

    detail.className =
        'algorithm-detail bucket-detail';

    detail.innerHTML = `
        <div class="algorithm-detail-title">
            Bucket Sort — Bucket View
        </div>

        <div class="algorithm-detail-note">
            When the common bucket formula is detected,
            this reference shows how the original input
            is distributed.
            The array animation remains the actual
            Java trace.
        </div>
    `;

    if (buckets) {
        const bucketGrid =
            document.createElement(
                'div'
            );

        bucketGrid.className =
            'bucket-grid';

        buckets.forEach(
            (bucket, index) => {
                const bucketEl =
                    document.createElement(
                        'div'
                    );

                bucketEl.className =
                    'bucket-column';

                bucketEl.innerHTML =
                    `<span class="bucket-title">` +
                    `Bucket ${index}` +
                    `</span>`;

                const valuesWrap =
                    document.createElement(
                        'div'
                    );

                valuesWrap.className =
                    'bucket-values';

                if (
                    bucket.length === 0
                ) {
                    valuesWrap.innerHTML =
                        '<span class="bucket-empty">empty</span>';

                } else {
                    bucket.forEach(
                        value => {
                            const chip =
                                document.createElement(
                                    'span'
                                );

                            chip.className =
                                'bucket-chip';

                            chip.textContent =
                                value;

                            valuesWrap.appendChild(
                                chip
                            );
                        }
                    );
                }

                bucketEl.appendChild(
                    valuesWrap
                );

                bucketGrid.appendChild(
                    bucketEl
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
            'A safe bucket-layout reference could not be inferred from this Java source; showing the actual array trace only.';

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


function updateStatus() {
    if (!executionSteps.length) {
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


function describeStep(step) {
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

    switch (step.type) {
        case 'condition':
            return indices.length
                ? `Comparing index ${indices.join(' and ')}`
                : 'Comparing';

        case 'write':
            return indices.length
                ? `Writing / shifting index ${indices.join(', ')}`
                : 'Writing / shifting';

        case 'swap':
            return indices.length === 2
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

        default:
            return 'Executing';
    }
}


function stepForward() {
    if (
        currentStepIndex <
        executionSteps.length - 1
    ) {
        visualizeStep(
            currentStepIndex + 1
        );
    }
}


function stepBackward() {
    if (
        currentStepIndex > 0
    ) {
        visualizeStep(
            currentStepIndex - 1
        );
    }
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
        [
            ...document
                .querySelectorAll(
                    'button'
                )
        ].find(
            b =>
                b.getAttribute(
                    'onclick'
                ) ===
                'pauseResume()'
        );

    if (button) {
        button.textContent =
            '▶ Play';
    }
}


function pauseResume() {
    const button =
        [
            ...document
                .querySelectorAll(
                    'button'
                )
        ].find(
            b =>
                b.getAttribute(
                    'onclick'
                ) ===
                'pauseResume()'
        );

    if (
        !executionSteps.length
    ) {
        return;
    }

    if (isPlaying) {
        stopPlayback();
        return;
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
                    executionSteps.length - 1
                ) {
                    stepForward();
                } else {
                    stopPlayback();
                }
            },
            animationSpeed
        );
}


function resetVisualization() {
    stopPlayback();

    currentStepIndex = 0;
    executionSteps = [];

    $('visualizationArea')
        .innerHTML = '';

    $('codeDisplay')
        .innerHTML = '';

    updateStatus();

    $('timeComplexity')
        .textContent = '-';

    $('spaceComplexity')
        .textContent = '-';

    if ($('executionMessage')) {
        setResult(
            'Ready.',
            '-',
            false
        );
    }

    clearError();
    clearInfo();
}


function analyzeComplexity(code) {
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
            /new\s+(?:int|Integer|Object)\s*\[/.test(
                code
            ) ||
            /new\s+ArrayList/.test(
                code
            );

        const maxDepth =
            approximateLoopDepth(
                code
            );

        if (
            hasRecursion &&
            /\bpivot\b/.test(
                code
            )
        ) {
            time =
                'O(n log n) average';

            space =
                hasAux
                    ? 'O(n)'
                    : 'O(log n) average';

        } else if (
            hasRecursion &&
            /(mid|\/\s*2|>>>\s*1)/.test(
                code
            )
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


function detectRecursion(code) {
    const methods =
        [
            ...code.matchAll(
                /(?:void|int\s*\[\s*\]|ArrayList\s*<[^>]+>)\s+(\w+)\s*\([^)]*\)\s*\{/g
            )
        ].map(
            m => m[1]
        );

    return methods.some(
        name =>
            new RegExp(
                `\\b${name}\\s*\\(`,
                'g'
            ).test(
                code.replace(
                    new RegExp(
                        `(?:void|int\\s*\\[\\s*\\]|ArrayList\\s*<[^>]+>)\\s+${name}\\s*\\([^)]*\\)`
                    ),
                    ''
                )
            )
    );
}


function approximateLoopDepth(code) {
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
                token.split(
                    '{'
                )[0];

            const isLoop =
                /\b(for|while)\s*\(/.test(
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

    /*
     * Fallback for formatting where
     * tokenization loses header association.
     */
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


function selectAlgorithm(type) {
    selectedAlgorithm = type;

    document
        .querySelectorAll(
            '.example-btn'
        )
        .forEach(
            btn =>
                btn.classList.remove(
                    'active'
                )
        );

    if (
        window.event &&
        window.event.target
    ) {
        window.event.target
            .classList.add(
                'active'
            );
    }

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

        bucket:
            'Bucket Sort',

        counting:
            'Counting Sort'
    };

    showInfo(
        `${names[type]} selected as a visualization/analysis mode. ` +
        `Execution still uses the Java code you pasted; ` +
        `the site never substitutes a built-in sorting implementation.`
    );

    const code =
        $('javaCode').value;

    if (
        code.trim()
    ) {
        analyzeComplexity(
            code
        );
    }

    if (
        executionSteps.length
    ) {
        visualizeStep(
            currentStepIndex
        );
    }
}
