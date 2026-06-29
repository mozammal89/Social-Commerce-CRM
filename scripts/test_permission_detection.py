#!/usr/bin/env python3
"""
Test script to see which permissions are being detected
"""

import re

# Read the demo views file
with open("apps/demo/views.py", "r") as f:
    content = f.read()

print("🔍 Testing permission detection patterns on demo views...")
print("=" * 80)

# Pattern 1: permission_required decorator
pattern1 = r'permission_required\(\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
matches1 = re.findall(pattern1, content)
print(f"\n📋 Pattern 1 (permission_required decorator): {len(matches1)} matches")
for match in sorted(matches1):
    print(f"   - {match}")

# Pattern 2: user_has_permission function
pattern2 = r'user_has_permission\([^,]+,\s*[^,]+,\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
matches2 = re.findall(pattern2, content)
print(f"\n📋 Pattern 2 (user_has_permission function): {len(matches2)} matches")
for match in sorted(matches2):
    print(f"   - {match}")

# Pattern 3: has_permission function
pattern3 = r'has_permission\([^,]+,\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
matches3 = re.findall(pattern3, content)
print(f"\n📋 Pattern 3 (has_permission function): {len(matches3)} matches")
for match in sorted(matches3):
    print(f"   - {match}")

# Pattern 4: Permission.objects.get with code
pattern4 = r'Permission\.objects\.get\(code\s*=\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
matches4 = re.findall(pattern4, content)
print(f"\n📋 Pattern 4 (Permission.objects.get): {len(matches4)} matches")
for match in sorted(matches4):
    print(f"   - {match}")

# Pattern 5: check_permission decorator (NEW PATTERN!)
pattern5 = r'check_permission\(\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
matches5 = re.findall(pattern5, content)
print(f"\n📋 Pattern 5 (check_permission decorator): {len(matches5)} matches")
for match in sorted(matches5):
    print(f"   - {match}")

# All matches combined
all_matches = set(matches1 + matches2 + matches3 + matches4 + matches5)
print(f"\n📊 TOTAL UNIQUE PERMISSIONS FOUND: {len(all_matches)}")
print("=" * 80)

# Expected permissions
expected_permissions = {
    "analytics.advanced_reports",
    "analytics.export",
    "analytics.live_data",
    "system.manage_integrations",
    "customers.bulk_operations",
}

print(f"\n🎯 EXPECTED PERMISSIONS: {len(expected_permissions)}")
for perm in sorted(expected_permissions):
    if perm in all_matches:
        print(f"   ✅ {perm}")
    else:
        print(f"   ❌ {perm} - NOT FOUND!")

print(f"\n🔍 MISSING PERMISSIONS:")
missing = expected_permissions - all_matches
if missing:
    for perm in sorted(missing):
        print(f"   ❌ {perm}")

        # Try to find where it should be
        if perm in content:
            print(f"      Found in file! Let's check the pattern...")
            # Show the lines containing this permission
            lines_with_perm = [line for line in content.split("\n") if perm in line]
            for line in lines_with_perm[:3]:  # Show first 3 matches
                print(f"      {line.strip()}")
        else:
            print(f"      NOT found in file at all!")
else:
    print("   ✅ All expected permissions found!")
