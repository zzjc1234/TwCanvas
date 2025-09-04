import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pytz  # Make sure you have this installed: pip install pytz
import requests
from tasklib import Task, TaskWarrior

# Initialize TaskWarrior instance
tw = TaskWarrior(taskrc_location="~/.taskrc")

# Set the Authorization header
headers = {"Authorization": "Bearer your token"}


def fetch_courses():
    response = requests.get(
        "https://oc.sjtu.edu.cn/api/v1/dashboard/dashboard_cards", headers=headers
    )
    return [
        {"id": course["id"], "name": course["courseCode"]} for course in response.json()
    ]


def fetch_assignments(course_id):
    response = requests.get(
        f"https://oc.sjtu.edu.cn/api/v1/courses/{course_id}/assignment_groups",
        headers=headers,
        params={
            "include[]": ["assignments", "discussion_topic"],
            "exclude_response_fields[]": ["description", "rubric"],
            "override_assignment_dates": "true",
        },
    )
    return response.json()


def extract_ass_id(task_description):
    matches = re.findall(r"#(\d+)", task_description)
    return matches[-1] if matches else None


def convert_due_date(due_date_str):
    """Convert due date to local time and return in ISO format"""
    if due_date_str is None or due_date_str == "null":
        return None

    # Define the local timezone
    local_tz = pytz.timezone("Asia/Singapore")  # Adjust this to your local timezone

    # Parse the due date string
    try:
        if due_date_str.endswith("Z"):
            # Handle UTC time
            utc_dt = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
            # Convert to local time
            local_dt = utc_dt.astimezone(local_tz)
            return local_dt.isoformat()  # Return as ISO string
        else:
            # Handle local time (assumed to be naive)
            naive_dt = datetime.fromisoformat(due_date_str)
            # Localize the naive datetime to the local timezone
            local_dt = local_tz.localize(naive_dt)
            return local_dt.isoformat()  # Return as ISO string
    except Exception as e:
        print(f"Error parsing due date: {due_date_str}, Error: {e}")
        return None


def comp_due(tk_due, ass_due_dt):
    """Check if the due dates are the same."""
    if tk_due is None and ass_due_dt is None:
        return True
    if tk_due is None or ass_due_dt is None:
        return False
    return tk_due.isoformat() == ass_due_dt


def determine_tags(description):
    keywords_to_tags = {
        "quiz": "quiz",
        "lab": "lab",
        "assignment": "hw",
        "homework": "hw",
        "midterm": "exam",
        "midtermexam": "exam",
        "mid": "exam",  # 注意：如果"mid"作为独立单词出现，现在才会匹配
        "final": "exam",
        "finalexam": "exam",
        "presentation": "pre",
        "presentation:": "pre",
    }

    # 将描述转换为小写，并根据空格分割成单词列表
    # 为了更快的查找效率，我们将其转换为一个集合 (set)
    description_words = set(description.lower().split())

    tags = {
        tag
        for keyword, tag in keywords_to_tags.items()
        if keyword in description_words  # 现在检查的是整个单词是否存在于分词后的集合中
    }

    # 原始逻辑：如果同时有 'exam' 和其他标签，则移除 'exam'
    if "exam" in tags and len(tags) > 1:
        tags.remove("exam")

    # 原始逻辑：如果没有匹配到任何标签，默认添加 "hw"
    return tags if tags else {"hw"}


def process_course(course):
    course_name = course["name"]
    course_id = course["id"]

    # Fetch assignments for the course
    assignments_data = fetch_assignments(course_id)

    # Skip if there are no assignments
    if not any(group.get("assignments") for group in assignments_data):
        return

    # Loop over assignments
    for group in assignments_data:
        for assignment in group.get("assignments", []):
            ass_name = assignment.get("name")
            ass_due = assignment.get("due_at")
            ass_id = assignment.get("id")

            # Convert due date to local time
            ass_due_dt = convert_due_date(ass_due)

            # Fetch existing tasks for the course
            task_cur = tw.tasks.filter(project=course_name)
            task_exists = False  # Flag to track if the task exists

            for existing_task in task_cur:
                tk_description = existing_task["description"].strip()
                tk_due = existing_task["due"]

                # Extract ass_id from the existing task's description
                existing_ass_id = extract_ass_id(tk_description)

                # Check if the existing task matches the current assignment ID
                if existing_ass_id == str(ass_id):
                    task_exists = True
                    tags = determine_tags(ass_name)
                    # Check if we need to update the task
                    if (
                        tk_description != ass_name + f" #{ass_id}"
                        or not comp_due(tk_due, ass_due_dt)
                        or not tags.issubset(existing_task["tags"])
                    ):
                        print(
                            f"Original task: {existing_task["description"]} with due data: {existing_task["due"]}"
                        )
                        existing_task["description"] = f"{ass_name} #{ass_id}"
                        existing_task["due"] = ass_due_dt  # Set due date to local time
                        existing_task["tags"] = list(
                            existing_task["tags"].union(set(tags))
                        )
                        if ass_due_dt is not None:
                            existing_task["wait"] = datetime.strptime(
                                ass_due, "%Y-%m-%dT%H:%M:%SZ"
                            ) - timedelta(days=14)
                        existing_task.save()
                        print(
                            f"Updated task: {tk_description} with due date: {ass_due_dt}"
                        )
                    break  # Exit loop if task exists

            # Add new task if it does not exist
            if not task_exists:
                new_task = Task(
                    tw,
                    description=f"{ass_name} #{ass_id}",
                    project=course_name,
                    priority="M",
                )
                new_task["tags"] = determine_tags(ass_name)
                if ass_due_dt:
                    new_task["due"] = ass_due_dt  # Set due date to local time
                    new_task["wait"] = datetime.strptime(
                        ass_due, "%Y-%m-%dT%H:%M:%SZ"
                    ) - timedelta(
                        days=14
                    )  # Set due date to local time
                new_task.save()
                print(
                    f"Added new task: {ass_name} #{ass_id} with due date: {ass_due_dt}"
                )


# Fetch courses
courses = fetch_courses()

# Use ThreadPoolExecutor to process courses in parallel
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(process_course, course): course for course in courses}
    for future in as_completed(futures):
        try:
            future.result()
        except Exception as e:
            print(f"Course processing generated an exception: {e}")
