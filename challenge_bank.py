from __future__ import annotations

import random
import secrets


LEGACY_VERSION = "sorting-15-v1"
VERSION = "sorting-15-v2"
ALGORITHMS = {
    "insertion": "Insertion sort",
    "selection": "Selection sort",
    "merge": "Merge sort",
    "quick": "Quick sort",
    "counting": "Counting sort",
    "bucket": "Bucket sort",
}
EXPLANATIONS = {
    "insertion": "A sorted prefix grows one element at a time. The next value is inserted into that prefix by moving larger neighbors to the right.",
    "selection": "Each pass scans the remaining suffix for its smallest value, then swaps that value into the next position in the sorted prefix.",
    "merge": "Small neighboring ranges are sorted and combined into larger sorted ranges. Values are written back as those ranges are merged.",
    "quick": "A pivot partitions a range: smaller values move to one side, the pivot moves into place, and the remaining ranges are processed recursively.",
    "counting": "The algorithm reads the input to count occurrences, then writes values in increasing order using those counts. No pairwise value comparisons are needed. The count table is deliberately hidden.",
    "bucket": "Values are grouped by value range, each group is sorted, and the groups are collected in order. Only the main array movements are shown; the group containers are deliberately hidden. A hidden-state trace is evidence for an identification, not a proof of a unique implementation.",
}


def make_questions(version=VERSION):
    if version not in (VERSION, LEGACY_VERSION):
        raise ValueError("Unsupported challenge test version")
    generator = random.Random(7315)
    questions = []
    for algorithm, count in (("insertion", 3), ("selection", 3), ("merge", 3),
                             ("quick", 2), ("counting", 2), ("bucket", 2)):
        for variant in range(count):
            values = generator.sample(range(10, 90), 9)
            if variant == 1:
                values[6] = values[2]
            questions.append({"id": f"q{len(questions) + 1:02d}",
                              "algorithm": algorithm, "values": values})
    for question in questions if version == VERSION else []:
        # Opaque IDs and independently shuffled order avoid encoding the key in
        # a choice value or keeping the right answer at a predictable position.
        choices = [{"id": secrets.token_hex(8), "text": EXPLANATIONS[name],
                    "correct": name == question["algorithm"]} for name in ALGORITHMS]
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


def grade(questions, answers):
    feedback = []
    for position, question in enumerate(questions):
        answer = answers[str(position)]
        correct = answer["identification"] == question["algorithm"]
        choices = question.get("reasoning_choices")
        reasoning_correct = bool(choices) and any(choice["id"] == answer["reasoning"] and choice["correct"]
                                                 for choice in choices)
        feedback.append({"number": position + 1, "correct": correct,
                         "reasoning_correct": reasoning_correct,
                         "selected_answer": ALGORITHMS[answer["identification"]],
                         "correct_answer": ALGORITHMS[question["algorithm"]],
                         "reasoning": next((choice["text"] for choice in choices or []
                                            if choice["id"] == answer["reasoning"]), answer["reasoning"]),
                         "explanation": EXPLANATIONS[question["algorithm"]]})
    multiple_choice = all("reasoning_choices" in question for question in questions)
    return {"score": sum(int(item["correct"]) + (int(item["reasoning_correct"]) if multiple_choice else 0)
                         for item in feedback),
            "total": len(questions) * (2 if multiple_choice else 1), "questions": feedback,
            "reasoning_status": "Automatically scored." if multiple_choice else "Saved for review; not automatically scored."}
