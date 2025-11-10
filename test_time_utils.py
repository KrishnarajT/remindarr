from datetime import datetime, timedelta
from app.utils.time_utils import calculate_next_trigger, parse_time_unit

def test_one_time_reminder():
    # One-time reminder in 30 minutes
    interval, next_time = calculate_next_trigger(30, 1, is_recurring=False)
    assert interval is None, "One-time reminder should have no interval"
    assert isinstance(next_time, datetime), "Should return a datetime"

def test_recurring_reminder():
    # Recurring reminder every 2 hours
    interval, next_time = calculate_next_trigger(2, 60, is_recurring=True)
    assert interval == 120, "Should be 120 minutes (2 hours)"
    assert isinstance(next_time, datetime), "Should return a datetime"

def test_parse_units():
    # Test various unit inputs
    assert parse_time_unit("minutes") == (1, "minutes")
    assert parse_time_unit("hours") == (60, "hours")
    assert parse_time_unit("days") == (60 * 24, "days")
    assert parse_time_unit("invalid") == (None, None)

if __name__ == "__main__":
    print("Running time utility tests...")
    
    print("1. Testing one-time reminder...")
    test_one_time_reminder()
    print("✓ One-time reminder test passed")
    
    print("2. Testing recurring reminder...")
    test_recurring_reminder()
    print("✓ Recurring reminder test passed")
    
    print("3. Testing unit parsing...")
    test_parse_units()
    print("✓ Unit parsing test passed")
    
    print("\nAll tests passed! ✨")