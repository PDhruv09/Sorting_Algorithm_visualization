from runner import execute_java

GOOD = '''
public static void insertionSort(int[] arr) {
    for (int i = 1; i < arr.length; i++) {
        int key = arr[i];
        int j = i - 1;
        while (j >= 0 && arr[j] > key) {
            arr[j + 1] = arr[j];
            j--;
        }
        arr[j + 1] = key;
    }
}
'''

BAD_COMPILE = '''
public static void sort(int[] arr) {
    int x = "not an int";
    for (int i = 0; i < arr.length; i++) {
        arr[i] = x;
    }
}
'''

BAD_RUNTIME = '''
public static void sort(int[] arr) {
    for (int i = 0; i < arr.length; i++) {
        arr[999] = i;
    }
}
'''

if __name__ == "__main__":
    ok = execute_java(GOOD, [5, 1, 4, 2, 8])
    assert ok["success"] and ok["finalArray"] == "[1, 2, 4, 5, 8]"
    assert len(ok["trace"]) > 2

    ce = execute_java(BAD_COMPILE, [3, 2, 1])
    assert not ce["success"] and ce["type"] == "compile_error"

    re = execute_java(BAD_RUNTIME, [3, 2, 1])
    assert not re["success"] and re["type"] == "runtime_error"

    print("Smoke tests passed.")
