// Global state
        let executionSteps = [];
        let currentStepIndex = 0;
        let isPlaying = false;
        let playInterval = null;
        let animationSpeed = 500;
        let testArray = [64, 34, 25, 12, 22, 11, 90, 88, 45, 50, 76, 33, 58, 92, 15, 38, 71, 29, 82, 47];
        let codeLines = [];

        // Create ArrayList-like object for compatibility with ArrayList-based Java code
        class ArrayList {
            constructor(arr) {
                this.data = [...arr];
            }
            
            get(index) {
                return this.data[index];
            }
            
            set(index, value) {
                this.data[index] = value;
            }
            
            size() {
                return this.data.length;
            }
            
            toArray() {
                return [...this.data];
            }
        }

        // Update speed
        document.getElementById('speedSlider').addEventListener('input', (e) => {
            animationSpeed = parseInt(e.target.value);
            document.getElementById('speedValue').textContent = animationSpeed + 'ms';
            if (isPlaying) {
                pauseResume();
                pauseResume();
            }
        });

        // Java Code Parser and Interpreter
        class JavaInterpreter {
            constructor(code, array) {
                this.code = code;
                this.array = [...array];
                this.steps = [];
                this.variables = new Map();
                this.comparisons = 0;
                this.swaps = 0;
                this.arrayAccesses = 0;
            }

            parse() {
                // Extract method body or use entire code
                let methodBody = this.extractMethodBody(this.code);
                codeLines = methodBody.split('\n').filter(line => line.trim());
                
                // Tokenize and execute
                this.execute(methodBody);
                return this.steps;
            }

            extractMethodBody(code) {
                // Try to extract method body from class
                const methodMatch = code.match(/void\s+sort\s*\([^)]*\)\s*\{([\s\S]*)\}/);
                if (methodMatch) {
                    return methodMatch[1];
                }
                
                // Check if it's already a method body
                if (code.includes('for') || code.includes('while') || code.includes('if')) {
                    return code;
                }
                
                return code;
            }

            execute(code) {
                // Replace arr with this.array for execution context
                let executableCode = code
                    .replace(/arr\[/g, 'this.array[')
                    .replace(/arr\.length/g, 'this.array.length');

                // Track initial state
                this.addStep('start', null, this.getCurrentArray(), 0);

                try {
                    // Parse and execute line by line
                    this.executeBlock(code, 0);
                } catch (e) {
                    console.error('Execution error:', e);
                }

                // Mark as complete
                this.addStep('complete', null, this.getCurrentArray(), codeLines.length - 1);
            }

            executeBlock(code, startLine) {
                const lines = code.split('\n');
                let lineNum = startLine;

                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i].trim();
                    if (!line || line.startsWith('//')) continue;

                    this.executeLine(line, lineNum);
                    lineNum++;
                }
            }

            executeLine(line, lineNum) {
                // Variable declaration
                if (line.match(/int\s+(\w+)\s*=\s*(.+);/)) {
                    const match = line.match(/int\s+(\w+)\s*=\s*(.+);/);
                    const varName = match[1];
                    const value = this.evaluateExpression(match[2]);
                    this.variables.set(varName, value);
                    this.addStep('variable', { name: varName, value }, this.getCurrentArray(), lineNum);
                }

                // For loop
                else if (line.match(/for\s*\(/)) {
                    this.executeForLoop(line, lineNum);
                }

                // While loop
                else if (line.match(/while\s*\(/)) {
                    this.executeWhileLoop(line, lineNum);
                }

                // If statement
                else if (line.match(/if\s*\(/)) {
                    this.executeIf(line, lineNum);
                }

                // Assignment
                else if (line.match(/(\w+)\s*=\s*(.+);/)) {
                    const match = line.match(/(\w+)\s*=\s*(.+);/);
                    const varName = match[1];
                    const value = this.evaluateExpression(match[2]);
                    this.variables.set(varName, value);
                    this.addStep('assignment', { name: varName, value }, this.getCurrentArray(), lineNum);
                }

                // Array swap pattern
                else if (line.match(/this\.array\[(\w+)\]\s*=\s*this\.array\[(\w+)\]/)) {
                    const match = line.match(/this\.array\[(\w+)\]\s*=\s*this\.array\[(\w+)\]/);
                    // This is part of a swap, handle in context
                }
            }

            executeForLoop(line, lineNum) {
                // Parse for loop: for (int i = 0; i < n; i++)
                const forMatch = line.match(/for\s*\(\s*(?:int\s+)?(\w+)\s*=\s*(.+?)\s*;\s*(\w+)\s*([<>=!]+)\s*(.+?)\s*;\s*(\w+)(\+\+|--|\s*=\s*.+?)\s*\)/);
                
                if (!forMatch) return;

                const [, varName, initValue, condVar, operator, limitExpr, updateVar, updateExpr] = forMatch;
                
                // Initialize loop variable
                let loopVar = this.evaluateExpression(initValue);
                this.variables.set(varName, loopVar);

                // Execute loop
                while (this.evaluateCondition(condVar, operator, limitExpr)) {
                    this.addStep('loop', { variable: varName, value: this.variables.get(varName) }, this.getCurrentArray(), lineNum);
                    
                    // Execute loop body (simplified - just look for next lines)
                    // In a real implementation, we'd parse the block structure
                    
                    // Update loop variable
                    if (updateExpr === '++') {
                        this.variables.set(varName, this.variables.get(varName) + 1);
                    } else if (updateExpr === '--') {
                        this.variables.set(varName, this.variables.get(varName) - 1);
                    }
                }
            }

            executeIf(line, lineNum) {
                // Parse if condition
                const condMatch = line.match(/if\s*\((.+)\)/);
                if (!condMatch) return;

                const condition = condMatch[1];
                
                // Detect comparison pattern
                const compMatch = condition.match(/this\.array\[(\w+)\]\s*([<>=!]+)\s*this\.array\[(\w+)\]/);
                if (compMatch) {
                    const [, idx1, op, idx2] = compMatch;
                    const i1 = this.evaluateExpression(idx1);
                    const i2 = this.evaluateExpression(idx2);
                    
                    this.comparisons++;
                    this.arrayAccesses += 2;
                    this.addStep('compare', { indices: [i1, i2] }, this.getCurrentArray(), lineNum);
                    
                    // Check if swap follows
                    const result = this.evaluateComparison(this.array[i1], op, this.array[i2]);
                    if (result) {
                        // Perform swap
                        this.swaps++;
                        this.arrayAccesses += 4;
                        [this.array[i1], this.array[i2]] = [this.array[i2], this.array[i1]];
                        this.addStep('swap', { indices: [i1, i2] }, this.getCurrentArray(), lineNum + 1);
                    }
                }
            }

            evaluateExpression(expr) {
                expr = expr.trim();
                
                // Check if it's a variable
                if (this.variables.has(expr)) {
                    return this.variables.get(expr);
                }
                
                // Check if it's array length
                if (expr === 'this.array.length' || expr === 'n') {
                    return this.array.length;
                }
                
                // Check if it's a number
                if (!isNaN(expr)) {
                    return parseInt(expr);
                }
                
                // Evaluate arithmetic expressions
                try {
                    // Replace variables in expression
                    let evalExpr = expr;
                    for (let [key, value] of this.variables) {
                        evalExpr = evalExpr.replace(new RegExp('\\b' + key + '\\b', 'g'), value);
                    }
                    evalExpr = evalExpr.replace(/this\.array\.length/g, this.array.length);
                    return eval(evalExpr);
                } catch (e) {
                    return 0;
                }
            }

            evaluateCondition(varName, operator, limitExpr) {
                const varValue = this.variables.get(varName);
                const limit = this.evaluateExpression(limitExpr);
                return this.evaluateComparison(varValue, operator, limit);
            }

            evaluateComparison(left, operator, right) {
                switch (operator) {
                    case '<': return left < right;
                    case '<=': return left <= right;
                    case '>': return left > right;
                    case '>=': return left >= right;
                    case '==': return left == right;
                    case '!=': return left != right;
                    default: return false;
                }
            }

            addStep(type, data, arrayState, lineNum) {
                this.steps.push({
                    type,
                    data,
                    array: arrayState,
                    lineNum,
                    comparisons: this.comparisons,
                    swaps: this.swaps,
                    arrayAccesses: this.arrayAccesses
                });
            }
        }

        // Simpler approach: Pattern-based execution for common sorting algorithms
        class PatternBasedExecutor {
            constructor(code, array) {
                this.code = code;
                this.usesArrayList = code.includes('ArrayList') || code.includes('.get(') || code.includes('.set(');
                
                // Use ArrayList wrapper if code uses ArrayList syntax
                if (this.usesArrayList) {
                    this.arrayList = new ArrayList(array);
                    this.array = this.arrayList.data; // Reference to underlying array for visualization
                } else {
                    this.array = [...array];
                }
                
                this.steps = [];
                this.comparisons = 0;
                this.swaps = 0;
                this.arrayAccesses = 0;
            }
            
            // Helper to get current array state for visualization
            getCurrentArray() {
                if (this.usesArrayList) {
                    return [...this.arrayList.data];
                }
                return this.getCurrentArray();
            }

            execute() {
                // Detect algorithm type
                if (this.code.includes('BubbleSort') || this.detectBubbleSort()) {
                    return this.executeBubbleSort();
                } else if (this.code.includes('SelectionSort') || this.detectSelectionSort()) {
                    return this.executeSelectionSort();
                } else if (this.code.includes('InsertionSort') || this.detectInsertionSort()) {
                    return this.executeInsertionSort();
                } else if (this.code.includes('MergeSort') || this.code.includes('merge')) {
                    return this.executeMergeSort();
                } else if (this.code.includes('QuickSort') || this.code.includes('quickSort') || this.code.includes('partition')) {
                    return this.executeQuickSort();
                }
                
                // Fallback: try generic execution
                return this.executeGeneric();
            }

            detectBubbleSort() {
                return this.code.match(/for.*for.*if.*(arr\[j\]|\.get\(j\)).*(arr\[j\s*\+\s*1\]|\.get\(j\s*\+\s*1\))/);
            }

            detectSelectionSort() {
                return this.code.match(/for.*for.*if.*(arr\[j\]|\.get\(j\)).*(arr\[|\.get\().*min/i);
            }

            detectInsertionSort() {
                return this.code.match(/for.*key.*while.*arr\[j\].*key/i);
            }

            executeBubbleSort() {
                const n = this.array.length;
                let lineNum = 0;
                
                this.addStep('start', null, this.getCurrentArray(), lineNum++);
                
                for (let i = 0; i < n - 1; i++) {
                    for (let j = 0; j < n - i - 1; j++) {
                        this.addStep('loop', { i, j }, this.getCurrentArray(), lineNum);
                        this.comparisons++;
                        this.arrayAccesses += 2;
                        
                        this.addStep('compare', { indices: [j, j + 1] }, this.getCurrentArray(), lineNum + 1);
                        
                        if (this.array[j] > this.array[j + 1]) {
                            this.swaps++;
                            this.arrayAccesses += 4;
                            [this.array[j], this.array[j + 1]] = [this.array[j + 1], this.array[j]];
                            this.addStep('swap', { indices: [j, j + 1] }, this.getCurrentArray(), lineNum + 2);
                        }
                    }
                    this.addStep('sorted', { index: n - i - 1 }, this.getCurrentArray(), lineNum + 3);
                }
                
                this.addStep('complete', null, this.getCurrentArray(), lineNum);
                return this.steps;
            }

            executeSelectionSort() {
                const n = this.array.length;
                let lineNum = 0;
                
                this.addStep('start', null, this.getCurrentArray(), lineNum++);
                
                for (let i = 0; i < n - 1; i++) {
                    let minIdx = i;
                    this.addStep('loop', { i, minIdx }, this.getCurrentArray(), lineNum);
                    
                    for (let j = i + 1; j < n; j++) {
                        this.comparisons++;
                        this.arrayAccesses += 2;
                        this.addStep('compare', { indices: [minIdx, j] }, this.getCurrentArray(), lineNum + 1);
                        
                        if (this.array[j] < this.array[minIdx]) {
                            minIdx = j;
                        }
                    }
                    
                    if (minIdx !== i) {
                        this.swaps++;
                        this.arrayAccesses += 4;
                        [this.array[i], this.array[minIdx]] = [this.array[minIdx], this.array[i]];
                        this.addStep('swap', { indices: [i, minIdx] }, this.getCurrentArray(), lineNum + 2);
                    }
                    
                    this.addStep('sorted', { index: i }, this.getCurrentArray(), lineNum + 3);
                }
                
                this.addStep('complete', null, this.getCurrentArray(), lineNum);
                return this.steps;
            }

            executeInsertionSort() {
                const n = this.array.length;
                let lineNum = 0;
                
                this.addStep('start', null, this.getCurrentArray(), lineNum++);
                
                for (let i = 1; i < n; i++) {
                    let key = this.array[i];
                    let j = i - 1;
                    
                    this.addStep('loop', { i, key }, this.getCurrentArray(), lineNum);
                    
                    while (j >= 0 && this.array[j] > key) {
                        this.comparisons++;
                        this.arrayAccesses += 3;
                        this.addStep('compare', { indices: [j, i] }, this.getCurrentArray(), lineNum + 1);
                        
                        this.array[j + 1] = this.array[j];
                        this.addStep('shift', { from: j, to: j + 1 }, this.getCurrentArray(), lineNum + 2);
                        j--;
                    }
                    
                    this.array[j + 1] = key;
                    this.addStep('insert', { index: j + 1, value: key }, this.getCurrentArray(), lineNum + 3);
                }
                
                this.addStep('complete', null, this.getCurrentArray(), lineNum);
                return this.steps;
            }

            executeMergeSort() {
                this.addStep('start', null, this.getCurrentArray(), 0);
                this.mergeSortHelper(0, this.array.length - 1, 1);
                this.addStep('complete', null, this.getCurrentArray(), 10);
                return this.steps;
            }

            mergeSortHelper(left, right, lineNum) {
                if (left < right) {
                    const mid = Math.floor((left + right) / 2);
                    this.addStep('divide', { left, mid, right }, this.getCurrentArray(), lineNum);
                    
                    this.mergeSortHelper(left, mid, lineNum + 1);
                    this.mergeSortHelper(mid + 1, right, lineNum + 2);
                    this.merge(left, mid, right, lineNum + 3);
                }
            }

            merge(left, mid, right, lineNum) {
                const leftArr = this.array.slice(left, mid + 1);
                const rightArr = this.array.slice(mid + 1, right + 1);
                
                let i = 0, j = 0, k = left;
                
                while (i < leftArr.length && j < rightArr.length) {
                    this.comparisons++;
                    this.arrayAccesses += 2;
                    this.addStep('compare', { indices: [left + i, mid + 1 + j] }, this.getCurrentArray(), lineNum);
                    
                    if (leftArr[i] <= rightArr[j]) {
                        this.array[k] = leftArr[i];
                        i++;
                    } else {
                        this.array[k] = rightArr[j];
                        j++;
                    }
                    this.addStep('merge', { index: k, value: this.array[k] }, this.getCurrentArray(), lineNum + 1);
                    k++;
                }
                
                while (i < leftArr.length) {
                    this.array[k] = leftArr[i];
                    this.addStep('merge', { index: k, value: this.array[k] }, this.getCurrentArray(), lineNum + 2);
                    i++;
                    k++;
                }
                
                while (j < rightArr.length) {
                    this.array[k] = rightArr[j];
                    this.addStep('merge', { index: k, value: this.array[k] }, this.getCurrentArray(), lineNum + 3);
                    j++;
                    k++;
                }
            }

            executeQuickSort() {
                this.addStep('start', null, this.getCurrentArray(), 0);
                this.quickSortHelper(0, this.array.length - 1, 1);
                this.addStep('complete', null, this.getCurrentArray(), 10);
                return this.steps;
            }

            quickSortHelper(low, high, lineNum) {
                if (low < high) {
                    const pi = this.partition(low, high, lineNum);
                    this.quickSortHelper(low, pi - 1, lineNum + 1);
                    this.quickSortHelper(pi + 1, high, lineNum + 2);
                }
            }

            partition(low, high, lineNum) {
                const pivot = this.array[high];
                this.addStep('pivot', { index: high, value: pivot }, this.getCurrentArray(), lineNum);
                
                let i = low - 1;
                
                for (let j = low; j < high; j++) {
                    this.comparisons++;
                    this.arrayAccesses += 2;
                    this.addStep('compare', { indices: [j, high] }, this.getCurrentArray(), lineNum + 1);
                    
                    if (this.array[j] < pivot) {
                        i++;
                        if (i !== j) {
                            this.swaps++;
                            this.arrayAccesses += 4;
                            [this.array[i], this.array[j]] = [this.array[j], this.array[i]];
                            this.addStep('swap', { indices: [i, j] }, this.getCurrentArray(), lineNum + 2);
                        }
                    }
                }
                
                this.swaps++;
                [this.array[i + 1], this.array[high]] = [this.array[high], this.array[i + 1]];
                this.addStep('swap', { indices: [i + 1, high] }, this.getCurrentArray(), lineNum + 3);
                
                return i + 1;
            }

            executeGeneric() {
                // Fallback: just show initial and final state
                this.addStep('start', null, this.getCurrentArray(), 0);
                
                // Attempt basic bubble sort as fallback
                return this.executeBubbleSort();
            }

            addStep(type, data, arrayState, lineNum) {
                this.steps.push({
                    type,
                    data,
                    array: arrayState,
                    lineNum,
                    comparisons: this.comparisons,
                    swaps: this.swaps,
                    arrayAccesses: this.arrayAccesses
                });
            }
        }

        function executeCode() {
            const code = document.getElementById('javaCode').value;
            
            // Validate code first
            const validation = validateCode(code);
            if (!validation.valid) {
                showError(validation.error);
                return;
            }
            
            // Clear any previous errors
            clearError();

            try {
                // Check if code uses ArrayList
                const usesArrayList = code.includes('ArrayList') || 
                                     (code.includes('.get(') && code.includes('.set('));
                
                if (usesArrayList) {
                    // Show info message
                    showInfo('Note: ArrayList detected. Using ArrayList-compatible execution with .get() and .set() methods.');
                }
                
                // Use pattern-based executor
                const executor = new PatternBasedExecutor(code, testArray);
                executionSteps = executor.execute();
                
                // Extract code lines for display
                const methodMatch = code.match(/\{([\s\S]*)\}/);
                if (methodMatch) {
                    codeLines = methodMatch[1].split('\n').filter(line => line.trim());
                } else {
                    codeLines = code.split('\n').filter(line => line.trim());
                }
                
                // Display code
                displayCode();
                
                // Analyze complexity based on actual code structure
                analyzeComplexity(code);
                
                // Reset and start
                currentStepIndex = 0;
                updateStatus();
                visualizeStep(0);
                
                // Auto-play
                pauseResume();
                
            } catch (error) {
                showError('Error executing code: ' + error.message);
                console.error('Full error:', error);
            }
        }

        function showError(message) {
            // Remove any existing error or info
            clearError();
            clearInfo();
            
            const errorDiv = document.createElement('div');
            errorDiv.className = 'error-message';
            errorDiv.id = 'error-display';
            errorDiv.textContent = message;
            
            const codeEditor = document.querySelector('.code-editor');
            codeEditor.appendChild(errorDiv);
        }

        function showInfo(message) {
            // Remove any existing info
            clearInfo();
            
            const infoDiv = document.createElement('div');
            infoDiv.className = 'info-message';
            infoDiv.id = 'info-display';
            infoDiv.textContent = message;
            
            const codeEditor = document.querySelector('.code-editor');
            codeEditor.appendChild(infoDiv);
        }

        function clearError() {
            const existingError = document.getElementById('error-display');
            if (existingError) {
                existingError.remove();
            }
        }

        function clearInfo() {
            const existingInfo = document.getElementById('info-display');
            if (existingInfo) {
                existingInfo.remove();
            }
        }

        function displayCode() {
            const codeDisplay = document.getElementById('codeDisplay');
            codeDisplay.innerHTML = '';
            
            codeLines.forEach((line, index) => {
                const lineDiv = document.createElement('div');
                lineDiv.className = 'code-line';
                lineDiv.innerHTML = `<span class="line-number">${index + 1}</span>${escapeHtml(line)}`;
                lineDiv.dataset.line = index;
                codeDisplay.appendChild(lineDiv);
            });
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function visualizeStep(index) {
            if (index < 0 || index >= executionSteps.length) return;
            
            const step = executionSteps[index];
            const visualArea = document.getElementById('visualizationArea');
            visualArea.innerHTML = '';
            
            // Calculate max value for scaling
            const maxValue = Math.max(...step.array);
            const maxHeight = 350;
            
            // Calculate optimal bar width based on array size
            const arraySize = step.array.length;
            const containerWidth = visualArea.clientWidth - 60; // Account for padding
            let barWidth;
            
            if (arraySize <= 20) {
                barWidth = Math.floor(containerWidth / arraySize) - 4; // 4px for gap
            } else if (arraySize <= 50) {
                barWidth = Math.max(12, Math.floor(containerWidth / arraySize) - 4);
            } else {
                // For large arrays, use fixed width and enable scroll
                barWidth = 10;
            }
            
            // Create bars
            step.array.forEach((value, idx) => {
                const bar = document.createElement('div');
                bar.className = 'bar';
                bar.style.height = (value / maxValue) * maxHeight + 'px';
                bar.style.width = barWidth + 'px';
                // Number label removed
                
                // Apply states
                if (step.type === 'compare' && step.data && step.data.indices.includes(idx)) {
                    bar.classList.add('comparing');
                } else if (step.type === 'swap' && step.data && step.data.indices.includes(idx)) {
                    bar.classList.add('swapping');
                } else if (step.type === 'sorted' && step.data && idx >= step.data.index) {
                    bar.classList.add('sorted');
                } else if (step.type === 'complete') {
                    bar.classList.add('sorted');
                }
                
                visualArea.appendChild(bar);
            });
            
            // Highlight code line
            document.querySelectorAll('.code-line').forEach(line => {
                line.classList.remove('executing');
            });
            
            const currentLine = document.querySelector(`[data-line="${step.lineNum}"]`);
            if (currentLine) {
                currentLine.classList.add('executing');
                currentLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            
            // Update status
            updateStatus();
        }

        function updateStatus() {
            if (executionSteps.length === 0) return;
            
            const step = executionSteps[currentStepIndex];
            document.getElementById('currentStep').textContent = currentStepIndex + 1;
            document.getElementById('totalSteps').textContent = executionSteps.length;
            document.getElementById('comparisons').textContent = step.comparisons;
            document.getElementById('swaps').textContent = step.swaps;
            document.getElementById('arrayAccesses').textContent = step.arrayAccesses;
        }

        function stepForward() {
            if (currentStepIndex < executionSteps.length - 1) {
                currentStepIndex++;
                visualizeStep(currentStepIndex);
            }
        }

        function stepBackward() {
            if (currentStepIndex > 0) {
                currentStepIndex--;
                visualizeStep(currentStepIndex);
            }
        }

        function pauseResume() {
            if (isPlaying) {
                isPlaying = false;
                clearInterval(playInterval);
                document.querySelector('.btn-info').textContent = '▶ Play';
            } else {
                isPlaying = true;
                document.querySelector('.btn-info').textContent = '⏸ Pause';
                playInterval = setInterval(() => {
                    if (currentStepIndex < executionSteps.length - 1) {
                        stepForward();
                    } else {
                        pauseResume();
                    }
                }, animationSpeed);
            }
        }

        function resetVisualization() {
            isPlaying = false;
            clearInterval(playInterval);
            currentStepIndex = 0;
            executionSteps = [];
            document.getElementById('visualizationArea').innerHTML = '';
            document.getElementById('codeDisplay').innerHTML = '';
            document.getElementById('currentStep').textContent = '0';
            document.getElementById('totalSteps').textContent = '0';
            document.getElementById('comparisons').textContent = '0';
            document.getElementById('swaps').textContent = '0';
            document.getElementById('arrayAccesses').textContent = '0';
            document.querySelector('.btn-info').textContent = '⏸ Pause';
        }

        function analyzeComplexity(code) {
            let timeComplexity = 'O(n)';
            let spaceComplexity = 'O(1)';
            
            // Count nested loops depth by analyzing structure
            const forLoops = (code.match(/for\s*\(/g) || []).length;
            const whileLoops = (code.match(/while\s*\(/g) || []).length;
            const totalLoops = forLoops + whileLoops;
            
            // Detect recursion
            const hasRecursion = /(\w+)\s*\([^)]*\)\s*\{[\s\S]*\1\s*\(/m.test(code);
            
            // Check for divide and conquer pattern (recursive with split)
            const hasDivideConquer = hasRecursion && 
                (code.includes('mid') || code.includes('pivot') || code.includes('/2') || code.includes('/ 2'));
            
            // Check for auxiliary data structures
            const hasAuxiliaryArray = code.match(/new\s+int\[/g);
            const auxiliaryArrayCount = hasAuxiliaryArray ? hasAuxiliaryArray.length : 0;
            
            // Analyze time complexity based on loop nesting
            if (hasDivideConquer) {
                // Merge sort, Quick sort pattern
                timeComplexity = 'O(n log n)';
                
                // Check space complexity
                if (auxiliaryArrayCount > 0 || code.includes('merge')) {
                    spaceComplexity = 'O(n)'; // Merge sort
                } else {
                    spaceComplexity = 'O(log n)'; // Quick sort (recursion stack)
                }
            } else if (hasRecursion) {
                // Recursive but not divide-conquer
                timeComplexity = 'O(n²)';
                spaceComplexity = 'O(n)';
            } else {
                // Analyze nested loops
                // Try to detect actual nesting depth
                let maxNestingDepth = 0;
                let currentDepth = 0;
                let inLoop = false;
                
                const lines = code.split('\n');
                for (let line of lines) {
                    if (line.match(/for\s*\(/) || line.match(/while\s*\(/)) {
                        currentDepth++;
                        inLoop = true;
                        maxNestingDepth = Math.max(maxNestingDepth, currentDepth);
                    }
                    if (line.includes('}') && inLoop) {
                        currentDepth = Math.max(0, currentDepth - 1);
                    }
                }
                
                // If we couldn't detect nesting properly, use loop count as approximation
                if (maxNestingDepth === 0) {
                    maxNestingDepth = Math.min(totalLoops, 3);
                }
                
                // Determine complexity based on nesting
                if (maxNestingDepth >= 3) {
                    timeComplexity = 'O(n³)';
                } else if (maxNestingDepth === 2) {
                    timeComplexity = 'O(n²)';
                } else if (maxNestingDepth === 1) {
                    timeComplexity = 'O(n)';
                } else {
                    timeComplexity = 'O(1)';
                }
                
                // Space complexity for iterative algorithms
                spaceComplexity = auxiliaryArrayCount > 0 ? 'O(n)' : 'O(1)';
            }
            
            document.getElementById('timeComplexity').textContent = timeComplexity;
            document.getElementById('spaceComplexity').textContent = spaceComplexity;
        }

        let selectedAlgorithm = null;

        function selectAlgorithm(type) {
            selectedAlgorithm = type;
            
            // Remove active class from all buttons
            document.querySelectorAll('.example-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            
            // Add active class to selected button
            event.target.classList.add('active');
            
            // Show selection feedback
            const algorithmNames = {
                bubble: 'Bubble Sort',
                selection: 'Selection Sort',
                insertion: 'Insertion Sort',
                merge: 'Merge Sort',
                quick: 'Quick Sort',
                bucket: 'Bucket Sort',
                counting: 'Counting Sort'
            };
            
            console.log(`Selected algorithm type: ${algorithmNames[type]}`);
        }

        function validateCode(code) {
            // Check if code is empty
            if (!code.trim()) {
                return { valid: false, error: 'Code cannot be empty!' };
            }
            
            // Check for random gibberish (must have some Java keywords)
            const javaKeywords = ['class', 'public', 'void', 'int', 'for', 'while', 'if', 'return', 'private', 'static'];
            const hasKeywords = javaKeywords.some(keyword => code.includes(keyword));
            
            if (!hasKeywords) {
                return { valid: false, error: 'Code does not appear to be valid Java code. Must contain Java keywords.' };
            }
            
            // Check for basic sorting structure
            const hasLoop = code.includes('for') || code.includes('while');
            
            // Check for array operations (traditional arrays OR ArrayList)
            const hasArrayBracket = code.includes('arr[') || code.includes('array[');
            const hasArrayList = code.includes('.get(') || code.includes('.set(');
            const hasArray = hasArrayBracket || hasArrayList;
            
            if (!hasLoop) {
                return { valid: false, error: 'Code must contain loops (for/while) for sorting.' };
            }
            
            if (!hasArray) {
                return { valid: false, error: 'Code must contain array operations (arr[...]) or ArrayList methods (.get/.set).' };
            }
            
            // Check for balanced braces
            const openBraces = (code.match(/\{/g) || []).length;
            const closeBraces = (code.match(/\}/g) || []).length;
            
            if (openBraces !== closeBraces) {
                return { valid: false, error: 'Unbalanced braces in code. Please check your syntax.' };
            }
            
            // Check for balanced parentheses
            const openParens = (code.match(/\(/g) || []).length;
            const closeParens = (code.match(/\)/g) || []).length;
            
            if (openParens !== closeParens) {
                return { valid: false, error: 'Unbalanced parentheses in code. Please check your syntax.' };
            }
            
            return { valid: true };
        }

        // Initialize
        window.addEventListener('load', () => {
            // Start with clean state
            resetVisualization();
        });
