import asyncio

from app.api.pairing import _pairing_lock


def test_pairing_serializes_contention_in_two_successive_event_loops():
    locks = []

    async def contend():
        lock = _pairing_lock()
        locks.append(lock)
        assert _pairing_lock() is lock
        entered = asyncio.Event()

        async def waiter():
            async with _pairing_lock():
                entered.set()

        async with lock:
            task = asyncio.create_task(waiter())
            await asyncio.sleep(0)
            assert not entered.is_set()
        await asyncio.wait_for(task, 1)
        assert entered.is_set()

    asyncio.run(contend())
    asyncio.run(contend())
    assert locks[0] is not locks[1]
