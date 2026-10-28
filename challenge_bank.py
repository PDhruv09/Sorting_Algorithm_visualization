from __future__ import annotations

import random
import secrets


LEGACY_VERSION = "sorting-15-v1"
PREVIOUS_VERSION = "sorting-15-v2"
VERSION = "sorting-15-v3"
SUPPORTED_VERSIONS = (LEGACY_VERSION, PREVIOUS_VERSION, VERSION)
ALGORITHMS = {
    "insertion": "Insertion sort",
    "selection": "Selection sort",
    "merge": "Merge sort",
    "quick": "Quick sort",
}
# Historical labels/traces remain available only for preserved v1/v2 attempts.
HISTORICAL_ALGORITHMS = {**ALGORITHMS, "counting": "Counting sort", "bucket": "Bucket sort"}


def algorithms_for_version(version):
    if version not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported challenge test version")
    return ALGORITHMS if version == VERSION else HISTORICAL_ALGORITHMS
EXPLANATIONS = {
    "insertion": "A sorted prefix grows one element at a time. The next value is inserted into that prefix by moving larger neighbors to the right.",
    "selection": "Each pass scans the remaining suffix for its smallest value, then swaps that value into the next position in the sorted prefix.",
    "merge": "Small neighboring ranges are sorted and combined into larger sorted ranges. Values are written back as those ranges are merged.",
    "quick": "A pivot partitions a range: smaller values move to one side, the pivot moves into place, and the remaining ranges are processed recursively.",
    "counting": "The algorithm reads the input to count occurrences, then writes values in increasing order using those counts. No pairwise value comparisons are needed. The count table is deliberately hidden.",
    "bucket": "Values are grouped by value range, each group is sorted, and the groups are collected in order. Only the main array movements are shown; the group containers are deliberately hidden. A hidden-state trace is evidence for an identification, not a proof of a unique implementation.",
}

# Each question gets a distinct wording for every choice. The same underlying
# evidence remains correct, while repeated answer text cannot serve as a key.
REASON_OPENINGS = {
    "insertion": (
        "The sorted section extends from the left as each new value is worked into place.",
        "A value from the unsorted side moves left through larger neighbors.",
        "The left prefix stays ordered while the next entry finds its position there.",
        "Larger entries shift right to make room for the value being inserted.",
        "One more entry joins an already ordered prefix on each pass.",
    ),
    "selection": (
        "A pass searches the remaining entries for the smallest value.",
        "The unsorted suffix is scanned before its minimum moves to the front.",
        "Each round chooses the least remaining entry for the next final position.",
        "The boundary of the sorted prefix advances after a minimum is selected.",
        "A minimum is located in the unfinished region and exchanged into place.",
    ),
    "merge": (
        "Small adjacent ordered ranges are combined into larger ordered ranges.",
        "Values from neighboring subranges are written back in sorted order.",
        "The trace builds sorted sections by joining smaller sections.",
        "Nearby sorted groups are repeatedly combined into a longer group.",
        "The array is assembled from ordered pieces of increasing size.",
    ),
    "quick": (
        "A pivot separates a range into values on either side of it.",
        "Partitioning places a chosen pivot before the remaining ranges are handled.",
        "A selected value divides the current region into smaller and larger sides.",
        "The trace rearranges one region around a pivot, then handles subregions.",
        "A pivot reaches its final location as the surrounding range is partitioned.",
    ),
    "counting": (
        "Input values are tallied before the array is rebuilt in increasing order.",
        "Occurrences of each value are counted and then used to write the output.",
        "The trace reads values for frequencies and writes values from those totals.",
        "A hidden frequency table guides the later writes into sorted order.",
        "The output is reconstructed from how often each value occurs.",
    ),
    "bucket": (
        "Values are grouped by range, ordered within groups, then gathered in range order.",
        "The trace fits range-based groups being sorted before they are collected.",
        "Values are distributed into hidden groups and later written back in group order.",
        "Each value belongs to a range group that is sorted before collection.",
        "The array is rebuilt by visiting ordered value-range groups in sequence.",
    ),
}
REASON_ENDINGS = {
    "insertion": ("The sorted prefix grows by one entry.", "Earlier ordered entries may shift right.", "The next entry is inserted among those already sorted."),
    "selection": ("The chosen minimum occupies the next position.", "The sorted prefix grows after that exchange.", "The remaining region is searched again on the next pass."),
    "merge": ("The combined region is written back in order.", "The ordered sections become progressively larger.", "The next combination uses those sorted pieces."),
    "quick": ("The smaller regions are then processed separately.", "Partitioning fixes the pivot's position.", "The same division repeats on the remaining ranges."),
    "counting": ("The frequency structure is not shown.", "The writes follow value counts rather than pairwise comparisons.", "Repeated values are emitted according to their counts."),
    "bucket": ("The group containers are hidden from view.", "The collected groups appear in value-range order.", "The intermediate range groups are not displayed."),
}


def reasoning_text(algorithm, question_index):
    return f"{REASON_OPENINGS[algorithm][question_index // 3]} {REASON_ENDINGS[algorithm][question_index % 3]}"


def make_questions(version=VERSION):
    algorithms = algorithms_for_version(version)
    generator = random.Random(7315)
    questions = []
    counts = ((("insertion", 4), ("selection", 4), ("merge", 4), ("quick", 3))
              if version == VERSION else
              (("insertion", 3), ("selection", 3), ("merge", 3),
               ("quick", 2), ("counting", 2), ("bucket", 2)))
    for algorithm, count in counts:
        for variant in range(count):
            values = generator.sample(range(10, 90), 9)
            if variant == 1:
                values[6] = values[2]
            questions.append({"id": f"q{len(questions) + 1:02d}",
                              "algorithm": algorithm, "values": values})
    for question_index, question in enumerate(questions if version != LEGACY_VERSION else []):
        # Opaque IDs and independently shuffled order avoid encoding the key in
        # a choice value or keeping the right answer at a predictable position.
        choices = [{"id": secrets.token_hex(8), "text": reasoning_text(name, question_index),
                    "correct": name == question["algorithm"]} for name in algorithms]
        secrets.SystemRandom().shuffle(choices)
        question["reasoning_choices"] = choices
    return questions


def animation(question):
    values = list(question["values"])
    frames = []

    def record(action, indices=()):
        frames.append({"values": list(values), "active": list(indices), "action": action})

    def swap(left, right):
        values[left], values[right] = values[right], values[left]
        record("swap", (left, right))

    def insertion(start, end):
        for position in range(start + 1, end):
            cursor = position
            while cursor > start:
                record("compare", (cursor - 1, cursor))
                if values[cursor - 1] <= values[cursor]:
                    break
                swap(cursor - 1, cursor)
                cursor -= 1

    def merge(start, end):
        if end - start < 2:
            return
        middle = (start + end) // 2
        merge(start, middle)
        merge(middle, end)
        left_values, right_values = values[start:middle], values[middle:end]
        left, right = 0, 0
        combined = []
        while left < len(left_values) and right < len(right_values):
            record("compare", (start + left, middle + right))
            if left_values[left] <= right_values[right]:
                combined.append(left_values[left])
                left += 1
            else:
                combined.append(right_values[right])
                right += 1
        combined.extend(left_values[left:])
        combined.extend(right_values[right:])
        for offset, value in enumerate(combined):
            values[start + offset] = value
            record("write", (start + offset,))

    def quick(start, end):
        if start >= end:
            return
        pivot = values[end]
        boundary = start
        for cursor in range(start, end):
            record("compare", (cursor, end))
            if values[cursor] < pivot:
                if cursor != boundary:
                    swap(cursor, boundary)
                boundary += 1
        if boundary != end:
            swap(boundary, end)
        quick(start, boundary - 1)
        quick(boundary + 1, end)

    record("ready")
    algorithm = question["algorithm"]
    if algorithm == "insertion":
        insertion(0, len(values))
    elif algorithm == "selection":
        for start in range(len(values) - 1):
            smallest = start
            for cursor in range(start + 1, len(values)):
                record("compare", (smallest, cursor))
                if values[cursor] < values[smallest]:
                    smallest = cursor
            if smallest != start:
                swap(start, smallest)
    elif algorithm == "merge":
        merge(0, len(values))
    elif algorithm == "quick":
        quick(0, len(values) - 1)
    elif algorithm == "counting":
        counts = [0] * (max(values) + 1)
        for position, value in enumerate(values):
            counts[value] += 1
            record("read", (position,))
        position = 0
        for value, count in enumerate(counts):
            for occurrence in range(count):
                values[position] = value
                record("write", (position,))
                position += 1
    elif algorithm == "bucket":
        groups = [[] for group in range(4)]
        minimum, maximum = min(values), max(values)
        for position, value in enumerate(values):
            group = min(3, (value - minimum) * 4 // (maximum - minimum + 1))
            groups[group].append(value)
            record("read", (position,))
        position = 0
        boundaries = []
        for group in groups:
            start = position
            for value in group:
                values[position] = value
                record("write", (position,))
                position += 1
            boundaries.append((start, position))
        for start, end in boundaries:
            insertion(start, end)
    else:
        raise ValueError("Unsupported challenge algorithm")
    record("complete")
    return frames


def public_question(question, position):
    result = {"number": position + 1, "frames": animation(question),
              "prompt": "Identify the sorting algorithm and choose the reasoning that best supports your answer."}
    if "reasoning_choices" in question:
        result["reasoning_choices"] = [{"id": choice["id"], "text": choice["text"]}
                                       for choice in question["reasoning_choices"]]
    else:
        result["prompt"] = "Identify the sorting algorithm and explain the movements that support your answer."
    return result


def grade(questions, answers, version=VERSION):
    algorithms = algorithms_for_version(version)
    feedback = []
    for position, question in enumerate(questions):
        answer = answers[str(position)]
        correct = answer["identification"] == question["algorithm"]
        choices = question.get("reasoning_choices")
        reasoning_correct = bool(choices) and any(choice["id"] == answer["reasoning"] and choice["correct"]
                                                 for choice in choices)
        feedback.append({"number": position + 1, "correct": correct,
                         "reasoning_correct": reasoning_correct,
                         "selected_answer": algorithms[answer["identification"]],
                         "correct_answer": algorithms[question["algorithm"]],
                         "reasoning": next((choice["text"] for choice in choices or []
                                            if choice["id"] == answer["reasoning"]), answer["reasoning"]),
                         "explanation": EXPLANATIONS[question["algorithm"]]})
    multiple_choice = all("reasoning_choices" in question for question in questions)
    if version == VERSION:
        for item in feedback:
            item["points"] = int(item["correct"] and item["reasoning_correct"])
            item["internal_points"] = (int(item["correct"]) + int(item["reasoning_correct"])) / 2
        return {"score": sum(item["points"] for item in feedback),
                "internal_score": sum(item["internal_points"] for item in feedback),
                "total": len(questions), "questions": feedback,
                "reasoning_status": "One point when identification and reasoning are both correct."}
    return {"score": sum(int(item["correct"]) + (int(item["reasoning_correct"]) if multiple_choice else 0)
                         for item in feedback),
            "total": len(questions) * (2 if multiple_choice else 1), "questions": feedback,
            "reasoning_status": "Automatically scored." if multiple_choice else "Saved for review; not automatically scored."}
