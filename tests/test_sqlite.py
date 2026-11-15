import datetime
import sqlite3

import pytest

from scrapyd.sqlite import JsonSqlitePriorityQueue, SqliteFinishedJobs
from tests import get_finished_job


@pytest.fixture
def jsonsqlitepriorityqueue():
    return JsonSqlitePriorityQueue()


@pytest.fixture
def sqlitefinishedjobs():
    q = SqliteFinishedJobs(":memory:")
    q.add(get_finished_job("p1", "s1", "j1", end_time=datetime.datetime(2001, 2, 3, 4, 5, 6, 7)))
    q.add(get_finished_job("p2", "s2", "j2", end_time=datetime.datetime(2001, 2, 3, 4, 5, 6, 8)))
    q.add(get_finished_job("p3", "s3", "j3", end_time=datetime.datetime(2001, 2, 3, 4, 5, 6, 9)))
    return q


def test_jsonsqlitepriorityqueue_empty(jsonsqlitepriorityqueue):
    assert jsonsqlitepriorityqueue.pop() is None


def test_jsonsqlitepriorityqueue_one(jsonsqlitepriorityqueue):
    msg = "a message"
    jsonsqlitepriorityqueue.put(msg)

    assert "_id" not in msg
    assert jsonsqlitepriorityqueue.pop() == msg
    assert jsonsqlitepriorityqueue.pop() is None


def test_jsonsqlitepriorityqueue_multiple(jsonsqlitepriorityqueue):
    msg1 = "first message"
    msg2 = "second message"
    jsonsqlitepriorityqueue.put(msg1)
    jsonsqlitepriorityqueue.put(msg2)
    out = []
    out.append(jsonsqlitepriorityqueue.pop())
    out.append(jsonsqlitepriorityqueue.pop())

    assert msg1 in out
    assert msg2 in out
    assert jsonsqlitepriorityqueue.pop() is None


def test_jsonsqlitepriorityqueue_priority(jsonsqlitepriorityqueue):
    msg1 = "message 1"
    msg2 = "message 2"
    msg3 = "message 3"
    msg4 = "message 4"
    jsonsqlitepriorityqueue.put(msg1, priority=1.0)
    jsonsqlitepriorityqueue.put(msg2, priority=5.0)
    jsonsqlitepriorityqueue.put(msg3, priority=3.0)
    jsonsqlitepriorityqueue.put(msg4, priority=2.0)

    assert jsonsqlitepriorityqueue.pop() == msg2
    assert jsonsqlitepriorityqueue.pop() == msg3
    assert jsonsqlitepriorityqueue.pop() == msg4
    assert jsonsqlitepriorityqueue.pop() == msg1


def test_jsonsqlitepriorityqueue_iter_len_clear(jsonsqlitepriorityqueue):
    assert len(jsonsqlitepriorityqueue) == 0
    assert list(jsonsqlitepriorityqueue) == []

    msg1 = "message 1"
    msg2 = "message 2"
    msg3 = "message 3"
    msg4 = "message 4"
    jsonsqlitepriorityqueue.put(msg1, priority=1.0)
    jsonsqlitepriorityqueue.put(msg2, priority=5.0)
    jsonsqlitepriorityqueue.put(msg3, priority=3.0)
    jsonsqlitepriorityqueue.put(msg4, priority=2.0)

    assert len(jsonsqlitepriorityqueue) == 4
    assert list(jsonsqlitepriorityqueue) == [(msg2, 5.0), (msg3, 3.0), (msg4, 2.0), (msg1, 1.0)]

    jsonsqlitepriorityqueue.clear()

    assert len(jsonsqlitepriorityqueue) == 0
    assert list(jsonsqlitepriorityqueue) == []


def test_jsonsqlitepriorityqueue_remove(jsonsqlitepriorityqueue):
    assert len(jsonsqlitepriorityqueue) == 0
    assert list(jsonsqlitepriorityqueue) == []

    msg1 = "good message 1"
    msg2 = "bad message 2"
    msg3 = "good message 3"
    msg4 = "bad message 4"
    jsonsqlitepriorityqueue.put(msg1)
    jsonsqlitepriorityqueue.put(msg2)
    jsonsqlitepriorityqueue.put(msg3)
    jsonsqlitepriorityqueue.put(msg4)
    jsonsqlitepriorityqueue.remove(lambda x: x.startswith("bad"))

    assert list(jsonsqlitepriorityqueue) == [(msg1, 0.0), (msg3, 0.0)]


@pytest.mark.parametrize(
    "value",
    [
        "native ascii str",
        "\xa3",
        123,
        1.2,
        True,
        ["a", "list", 1],
        {"a": "dict"},
    ],
)
def test_jsonsqlitepriorityqueue_types(jsonsqlitepriorityqueue, value):
    jsonsqlitepriorityqueue.put(value)

    assert jsonsqlitepriorityqueue.pop() == value


def test_sqlitefinishedjobs_add(sqlitefinishedjobs):
    assert len(sqlitefinishedjobs) == 3


def test_sqlitefinishedjobs_clear_all(sqlitefinishedjobs):
    sqlitefinishedjobs.clear()

    assert len(sqlitefinishedjobs) == 0


def test_sqlitefinishedjobs_clear_keep_0(sqlitefinishedjobs):
    sqlitefinishedjobs.clear(finished_to_keep=0)

    assert len(sqlitefinishedjobs) == 0


def test_sqlitefinishedjobs_clear_keep_2(sqlitefinishedjobs):
    sqlitefinishedjobs.clear(finished_to_keep=2)

    assert len(sqlitefinishedjobs) == 2


def test_sqlitefinishedjobs__iter__(sqlitefinishedjobs):
    actual = list(sqlitefinishedjobs)

    assert (actual[0][0], actual[0][1]) == ("p3", "s3")
    assert (actual[1][0], actual[1][1]) == ("p2", "s2")
    assert (actual[2][0], actual[2][1]) == ("p1", "s1")


def test_sqlitefinishedjobs_launch_roundtrip():
    q = SqliteFinishedJobs(":memory:")
    job = get_finished_job("p1", "s1", "j1", end_time=datetime.datetime(2001, 2, 3, 4, 5, 6, 7))
    launch = {"version": "0.1", "settings": {"DOWNLOAD_DELAY": "2"}, "args": {"arg1": "val1"}}
    job.launch = launch

    q.add(job)

    row = next(iter(q))
    assert row[5] == launch


def test_sqlitefinishedjobs_migrates_legacy_table(tmp_path):
    """A table created before launch parameters were persisted gets a nullable launch column, and stays readable."""
    database = str(tmp_path / "legacy.db")

    # Create and populate a table using the old schema (no launch column).
    start = datetime.datetime(2001, 2, 3, 4, 5, 6, 7)
    end = datetime.datetime(2001, 2, 3, 4, 5, 6, 8)
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE finished_jobs "
        "(id integer PRIMARY KEY, project text, spider text, job text, start_time datetime, end_time datetime)"
    )
    conn.execute(
        "INSERT INTO finished_jobs (project, spider, job, start_time, end_time) VALUES (?, ?, ?, ?, ?)",
        ("p1", "s1", "j1", start, end),
    )
    conn.commit()
    conn.close()

    # Opening the storage migrates the schema and reads the legacy row without error.
    q = SqliteFinishedJobs(database, "finished_jobs")

    actual = list(q)
    assert len(actual) == 1
    project, spider, jobid, start_time, end_time, launch = actual[0]
    assert (project, spider, jobid) == ("p1", "s1", "j1")
    assert start_time == start
    assert end_time == end
    # Legacy rows have no launch parameters and decode to the documented empty shape.
    assert launch == {"version": None, "settings": {}, "args": {}}

    # New rows persist their launch parameters alongside the migrated legacy row.
    new_job = get_finished_job("p2", "s2", "j2", end_time=end + datetime.timedelta(seconds=1))
    new_job.launch = {"version": "0.2", "settings": {"ONE": "two"}, "args": {"arg": "val"}}
    q.add(new_job)

    by_job = {row[2]: row[5] for row in q}
    assert by_job["j2"] == {"version": "0.2", "settings": {"ONE": "two"}, "args": {"arg": "val"}}
    assert by_job["j1"] == {"version": None, "settings": {}, "args": {}}
