# Complete RBAC System Guide
**Understanding Permissions, Stores, and User Access**

---

## Table of Contents
1. [Understanding the Permission Models](#1-understanding-the-permission-models)
2. [How Users Connect to Stores](#2-how-users-connect-to-stores)
3. [Complete Customer Flow (Start to Finish)](#3-complete-customer-flow-start-to-finish)
4. [System Admin Guide](#4-system-admin-guide)
5. [Full Customer Journey](#5-full-customer-journey)
6. [Customer Quick Start Guide](#6-customer-quick-start-guide)
7. [How Permissions Work (Simplified)](#7-how-permissions-work-simplified)

---

## 1. Understanding the Permission Models

### The Big Picture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           THE RBAC ECOSYSTEM                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐      ┌──────────┐            │
│  │   USER   │──────│  STORE   │──────│   PLAN   │──────│ FEATURE  │            │
│  │          │      │          │      │          │      │          │            │
│  │ "Who?"  │      │ "Where?" │      │ "What    │      │ "Which   │            │
│  │          │      │          │      │ tier?"   │      │ tools?"  │            │
│  └─────┬────┘      └─────┬────┘      └─────┬────┘      └─────────┘            │
│        │                  │                  │                                   │
│        └──────────────────┴──────────────────┴────────────┐                    │
│                                                             │                    │
│                                                             ▼                    │
│                                                  ┌──────────────────┐            │
│                                                  │    ROLE         │            │
│                                                  │                 │            │
│                                                  │ "What can they  │            │
│                                                  │  do here?"      │            │
│                                                  └────────┬─────────┘            │
│                                                           │                      │
│                                                           ▼                      │
│                                                  ┌──────────────────┐            │
│                                                  │  PERMISSION     │            │
│                                                  │                 │            │
│                                                  │ "Exact action"  │            │
│                                                  └──────────────────┘            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Model-by-Model Explanation

---

#### **Resource**
**Purpose:** Defines WHAT things exist in the system that need protection.

**Think of it as:** A category of items (like "Products", "Customers", "Orders")

**Real-world example:** 
- "Customers" is a resource
- "Products" is a resource
- "Orders" is a resource

**How it's used:**
```python
Resource: "Customers"
  ├─ Can be viewed
  ├─ Can be created
  ├─ Can be updated
  └─ Can be deleted
```

---

#### **Permission**
**Purpose:** Defines EXACTLY what action can be done on a resource.

**Think of it as:** A specific right or ability (like "Create Customer")

**Real-world example:**
- `customers.view` - Can see customer list
- `customers.create` - Can add new customers
- `customers.update` - Can edit customer info
- `customers.delete` - Can remove customers

**How it's related to customer/store:**
When a user tries to do something, the system checks:
> "Does this user have the `customers.create` permission for this store?"

---

#### **Role**
**Purpose:** Bundles permissions together into a job title.

**Think of it as:** A job position (like "Manager", "Sales Agent", "Viewer")

**Real-world example:**
```
Role: "Manager"
  Has permissions to:
  ├── customers.view
  ├── customers.create
  ├── customers.update
  ├── orders.view
  ├── orders.create
  └── reports.view
```

**How it's related to customer/store:**
- Each user in a store has ONE role (or more)
- The role determines what they CAN and CANNOT do
- System roles exist globally (Store Owner, Admin, Manager, etc.)
- Custom roles can be created per store

**System Roles (pre-defined):**

| Role | Level | Description |
|------|-------|-------------|
| Store Owner | 100 | Can do EVERYTHING |
| Admin | 80 | Can do everything except transfer ownership |
| Manager | 60 | Day-to-day operations |
| Sales Agent | 40 | Manage own sales pipeline |
| Customer Support | 35 | Read and reply to customers |
| Inventory Manager | 40 | Manage stock and warehouses |
| Marketing Executive | 40 | Run campaigns and promos |
| Accountant | 40 | View orders and reports |
| Viewer | 20 | Read-only access |

---

#### **RolePermission**
**Purpose:** Connects roles to permissions with a modifier.

**Think of it as:** The rule book that says "This role can do this"

**Real-world example:**
```
Role: "Sales Agent"
├── RolePermission: orders.create (GRANT) ✓
├── RolePermission: customers.view (GRANT) ✓
└── RolePermission: settings.update (DENY) ✗
```

**Modifiers:**
- **GRANT**: Explicitly allows the permission
- **DENY**: Explicitly forbids the permission (always wins!)
- **DEFAULT**: Inherits from parent role

**How it's related to customer/store:**
When a user is assigned a role in a store, they get ALL the permissions that role grants (and all the denies).

---

#### **StoreMembership**
**Purpose:** Connects a USER to a STORE with a ROLE.

**Think of it as:** An employment contract or membership card

**Real-world example:**
```
StoreMembership:
  User: John Smith
  Store: Acme Electronics
  Role: Sales Agent
  Active: Yes
  Joined: Jan 15, 2024
```

**How it's related to customer/store:**
- This is the CORE connection model
- Without this, a user CANNOT access a store
- One user can belong to MULTIPLE stores (with different roles)
- Can be deactivated (like terminating employment)

---

#### **UserPermissionOverride**
**Purpose:** Special exception for a specific user.

**Think of it as:** A special privilege or restriction for ONE person

**Real-world example:**
```
Scenario: Sarah is normally a Viewer, but needs to export reports once

UserPermissionOverride:
  User: Sarah Johnson
  Store: Acme Electronics
  Permission: reports.export
  Is Granted: Yes
  Expires: Tomorrow at midnight
```

**How it's related to customer/store:**
- Used for temporary access
- Used for special cases
- DENY overrides are absolute (user CANNOT do this, regardless of role)
- Can be store-specific OR global (applies to all stores)

---

#### **Feature**
**Purpose:** Represents a capability that can be turned on/off based on subscription plan.

**Think of it as:** A feature flag or module

**Real-world example:**
- `marketing_campaigns` - Ability to create email campaigns
- `multi_warehouse` - Ability to manage multiple warehouses
- `api_access` - Ability to use API

**How it's related to customer/store:**
A store can ONLY use features included in their subscription plan.

---

#### **SubscriptionPlan**
**Purpose:** Defines pricing tiers and what features are included.

**Think of it as:** Pricing package (like Basic, Pro, Enterprise)

**Real-world example:**
```
Plan: "Growth"
  Price: $49/month
  Max users: 10
  Max stores: 3
  Max products: 5,000
  Features:
    ├── customer_management ✓
    ├── inventory_management ✓
    ├── marketing_campaigns ✓
    ├── advanced_reports ✓
    └── sso ✗ (not included)
```

**How it's related to customer/store:**
Every store has a subscription that determines:
1. What features they can use
2. What limits they have (users, products, etc.)

---

#### **PlanFeature**
**Purpose:** Connects plans to features (with optional limits).

**Think of it as:** The feature list for each pricing tier

**Real-world example:**
```
PlanFeature:
  Plan: Starter
  Feature: marketing_campaigns
  Limit Value: 1 (only 1 active campaign allowed)
```

**How it's related to customer/store:**
When a store tries to use a feature, the system checks:
> "Does this store's plan include this feature? Are they within the limit?"

---

#### **Subscription**
**Purpose:** Tracks a store's current billing status and plan.

**Think of it as:** The active subscription record

**Real-world example:**
```
Subscription:
  Store: Acme Electronics
  Plan: Growth
  Status: active
  Started: Jan 1, 2024
  Period end: Feb 1, 2024
  Trial ends: Jan 15, 2024
```

**How it's related to customer/store:**
- One subscription per store
- Determines if features are accessible
- Can be trialing, active, past_due, canceled, or expired

---

#### **AuditLog**
**Purpose:** Records every change to permissions, roles, and memberships.

**Think of it as:** A security camera recording all access changes

**Real-world example:**
```
AuditLog:
  Action: role.update
  Actor: admin@company.com
  Target: Manager role
  Before: {...old state...}
  After: {...new state...}
  IP: 192.168.1.100
  Time: 2024-01-15 10:30:00
```

**How it's related to customer/store:**
- Tracks WHO changed WHAT
- Tracks WHEN changes happened
- Helps with security audits
- Cannot be deleted or modified (append-only)

---

## 2. How Users Connect to Stores

### The Connection Model

```
┌──────────────┐                 ┌──────────────┐
│              │                 │              │
│    USER      │                 │    STORE     │
│              │                 │              │
│ "John Smith" │                 │ "Acme Inc."  │
│              │                 │              │
└──────┬───────┘                 └──────▲───────┘
       │                               │
       │    ┌──────────────────────────┘
       │    │
       │    │
       ▼    ▼
┌──────────────────────┐
│                      │
│  StoreMembership     │
│                      │
│  ┌────────────────┐ │
│  │ Role: Manager  │ │
│  │ Active: Yes    │ │
│  │ Joined: Jan 15 │ │
│  └────────────────┘ │
└──────────────────────┘
```

### Connection Methods

There are THREE ways a user can be connected to a store:

#### **Method 1: Through Legacy Fields (Old System)**
```python
# Still supported for backward compatibility
store.owners.add(user)      # User is an owner
store.managers.add(user)    # User is a manager
store.staff.add(user)      # User is staff
```

#### **Method 2: Through StoreMembership (New RBAC System)**
```python
# The modern way
from apps.permissions.models import StoreMembership, Role

StoreMembership.objects.create(
    user=user,
    store=store,
    role=Role.objects.get(slug="manager")
)
```

#### **Method 3: Through Invitation**
```python
from apps.permissions.services import add_member

# Owner invites team member
add_member(
    user=new_user,
    store=store,
    role=Role.objects.get(slug="sales-agent"),
    invited_by=request.user
)
```

### Multi-Store Access

A user can belong to MULTIPLE stores:

```
                    ┌──────────────┐
                    │              │
                    │   USER       │
                    │ "John Smith" │
                    │              │
                    └──────┬───────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Store A    │  │   Store B    │  │   Store C    │
│              │  │              │  │              │
│ "Acme Inc."  │  │ "Beta Corp." │  │ "Gamma LLC"  │
│              │  │              │  │              │
│ Role: Owner  │  │ Role: Admin  │  │ Role: Viewer │
└──────────────┘  └──────────────┘  └──────────────┘
```

When John logs in:
1. System finds ALL stores he belongs to
2. John selects which store to work with
3. His permissions are checked for THAT STORE only

---

## 3. Complete Customer Flow (Start to Finish)

### Phase 1: Registration (User Creation)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          STEP 1: USER REGISTRATION                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. User visits signup page                                                     │
│  2. Enters: name, email, password                                              │
│  3. System creates User account                                                  │
│  4. User can now log in                                                         │
│                                                                                 │
│  Result: User exists, but NO store access yet                                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          STEP 2: EMAIL VERIFICATION                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. System sends verification email                                            │
│  2. User clicks verification link                                               │
│  3. Account marked as verified                                                 │
│                                                                                 │
│  Result: User is fully active                                                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 2: Store Creation

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          STEP 3: CREATE FIRST STORE                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. User clicks "Create Store"                                                 │
│  2. Enters store details:                                                       │
│     - Store name                                                               │
│     - Business type                                                            │
│     - Contact info                                                              │
│  3. System creates:                                                            │
│     ✓ Store record                                                             │
│     ✓ Subscription (trialing status)                                           │
│     ✓ StoreMembership (user as Store Owner)                                    │
│                                                                                 │
│  Result: User has full access to their new store                                │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          STEP 4: SELECT PLAN                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  User chooses subscription plan:                                                │
│                                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  STARTER    │  │   GROWTH    │  │PROFESSIONAL │  │ ENTERPRISE  │            │
│  │   $19/mo    │  │   $49/mo    │  │   $99/mo    │  │  $299/mo    │            │
│  │             │  │             │  │             │  │             │            │
│  │ • 3 users   │  │ • 10 users  │  │ • 25 users  │  │ • Unlimited │            │
│  │ • 1 store   │  │ • 3 stores  │  │ • 10 stores │  │ • Unlimited │            │
│  │ • Basic     │  │ • Advanced  │  │ • Premium   │  │ • Everything│            │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘            │
│                                                                                 │
│  Result: Store's subscription is created with plan limits                       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 3: Team Setup

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          STEP 5: INVITE TEAM MEMBERS                           │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  As Store Owner, user can:                                                      │
│                                                                                 │
│  1. Go to Team Management                                                       │
│  2. Click "Invite Member"                                                      │
│  3. Enter: email, select role                                                  │
│  4. System sends invitation email                                              │
│  5. New user accepts invitation → Gets StoreMembership                          │
│                                                                                 │
│  Roles available to assign:                                                     │
│  ┌─────────────────┐                                                           │
│  │ • Store Owner    │ (Full access)                                           │
│  │ • Admin          │ (All except ownership transfer)                         │
│  │ • Manager        │ (Day-to-day operations)                                 │
│  │ • Sales Agent    │ (Sales pipeline)                                       │
│  │ • Customer Supp.  │ (Customer service)                                     │
│  │ • Inventory Mgr  │ (Stock management)                                     │
│  │ • Marketing Exec │ (Campaigns)                                            │
│  │ • Accountant     │ (Reports & finance)                                    │
│  │ • Viewer         │ (Read-only)                                            │
│  └─────────────────┘                                                           │
│                                                                                 │
│  Check: User count must be within plan limit                                   │
│                                                                                 │
│  Result: Team members have access with specific roles                          │
│                                                                                 │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          STEP 6: CUSTOMIZE PERMISSIONS (OPTIONAL)                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  Store Owner can:                                                               │
│                                                                                 │
│  1. Create custom roles:                                                       │
│     - Clone existing role                                                       │
│     - Add/remove permissions                                                     │
│     - Assign to team members                                                    │
│                                                                                 │
│  2. Create special overrides:                                                   │
│     - Grant temporary access                                                    │
│     - Deny specific permissions                                                 │
│                                                                                 │
│  Result: Fine-tuned access control                                              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 4: Daily Operations

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          STEP 7: USING THE SYSTEM                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  Every action is checked:                                                       │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ User wants to CREATE ORDER                                               │    │
│  │                                                                          │    │
│  │ System checks:                                                           │    │
│  │ 1. ✓ User is logged in                                                   │    │
│  │ 2. ✓ User has active store membership                                    │    │
│  │ 3. ✓ Store's plan has "orders" feature                                   │    │
│  │ 4. ✓ User's role grants "orders.create" permission                       │    │
│  │ 5. ✓ No DENY overrides                                                   │    │
│  │                                                                          │    │
│  │ Result: ACCESS ALLOWED ✓                                                │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ User wants to EXPORT REPORTS (not in plan)                               │    │
│  │                                                                          │    │
│  │ System checks:                                                           │    │
│  │ 1. ✓ User is logged in                                                   │    │
│  │ 2. ✓ User has active store membership                                    │    │
│  │ 3. ✗ Store's plan does NOT have "advanced_reports" feature              │    │
│  │                                                                          │    │
│  │ Result: ACCESS DENIED ✗                                                  │    │
│  │         Message: "Upgrade to Professional to access advanced reports"   │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. System Admin Guide

### Who is a System Admin?

A System Admin (Superuser) has:
- Access to ALL stores
- Can bypass ALL permission checks
- Can modify ANY RBAC configuration
- Full access to Django admin panel

### Admin Capabilities

#### **1. View All Stores**
```
Admin Panel → Stores Section
├── View all stores in system
├── See store subscription status
├── See store plan and limits
└── View store owner and team
```

#### **2. View All Users**
```
Admin Panel → Users Section
├── View all registered users
├── See which stores each user belongs to
├── View user's roles in each store
└── Manage user status (active/suspended)
```

#### **3. Manage Store Subscriptions**
```
Admin Panel → Subscriptions
├── Change store's plan
├── Extend trial periods
├── Manually adjust subscription dates
├── Fix payment issues
└── Cancel subscriptions
```

#### **4. Manage Roles (System-Wide)**
```
Admin Panel → Roles
├── View all system roles
├── See role permissions
├── Create new system roles
├── Modify existing role permissions
└── Deactivate roles

Note: System roles apply to ALL stores
```

#### **5. View Audit Logs**
```
Admin Panel → Audit Logs
├── Filter by store
├── Filter by user
├── Filter by action type
├── Export to CSV
└── Investigate security issues
```

#### **6. Emergency Access Recovery**
```
When a user is locked out:

Option 1: Direct Access
├── Admin can access any store directly
├── Can fix membership issues
└── Can create emergency overrides

Option 2: Database Fix
├── Directly modify StoreMembership
├── Remove DENY overrides
├── Fix subscription status
└── Adjust role assignments
```

### Common Admin Tasks

#### **Task 1: Help Locked-Out User**
```python
# 1. Check audit log for recent changes
AuditLog.objects.filter(actor=user).order_by('-created_at')

# 2. Check active memberships
StoreMembership.objects.filter(user=user, is_active=True)

# 3. If membership was deactivated, reactivate:
membership.is_active = True
membership.save()

# 4. If DENY override was applied, remove it:
UserPermissionOverride.objects.filter(
    user=user,
    is_granted=False
).delete()
```

#### **Task 2: Upgrade Store Plan**
```python
from apps.permissions.models import Subscription, SubscriptionPlan

store = Store.objects.get(id=store_id)
new_plan = SubscriptionPlan.objects.get(slug='professional')

subscription = store.subscription
subscription.plan = new_plan
subscription.save()

# System automatically:
# - Updates feature access
# - Increases limits
# - Logs the change
```

#### **Task 3: Transfer Store Ownership**
```python
from apps.permissions.models import StoreMembership, Role

old_owner = User.objects.get(email='old@example.com')
new_owner = User.objects.get(email='new@example.com')
store = Store.objects.get(id=store_id)
owner_role = Role.objects.get(slug='store-owner')

# Remove old owner's owner role
StoreMembership.objects.filter(
    user=old_owner,
    store=store,
    role=owner_role
).delete()

# Add new owner role
StoreMembership.objects.create(
    user=new_owner,
    store=store,
    role=owner_role
)
```

#### **Task 4: Investigate Security Issue**
```python
# Get all recent changes for a store
recent_audit = AuditLog.objects.filter(
    store=store
).order_by('-created_at')[:100]

# Look for suspicious patterns:
# - Multiple role changes
# - Unexpected permission grants
# - New memberships created
# - Plan changes

# Export for analysis
import csv
# ... export code ...
```

---

## 5. Full Customer Journey

### Story: Sarah's Journey with Social Commerce CRM

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          SARAH'S COMPLETE JOURNEY                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 1: Discovery & Sign Up
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  9:00 AM  │ Sarah discovers Social Commerce CRM via Google search              │
│  9:15 AM  │ She clicks "Get Started Free" on the website                        │
│  9:20 AM  │ Registration page:                                                  │
│           │   - Name: Sarah Johnson                                            │
│           │   - Email: sarah@bloomflow.com                                     │
│           │   - Password: ••••••••                                             │
│  9:22 AM  │ ✓ Account created! Email verification sent                        │
│  9:25 AM  │ Sarah clicks verification link in her email                        │
│  9:26 AM  │ ✓ Email verified! She's now logged in                              │
│  9:27 AM  │ Welcome screen: "Create your first store"                         │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 1: Store Creation
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  9:30 AM  │ Sarah enters store details:                                         │
│           │   - Store name: Bloomflow                                          │
│           │   - Business: Floral e-commerce                                    │
│           │   - Phone: (555) 123-4567                                          │
│  9:32 AM  │ ✓ Store created!                                                   │
│  9:33 AM  │ Plan selection page displays:                                       │
│           │                                                                     │
│           │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│           │   │   STARTER    │  │   GROWTH     │  │PROFESSIONAL  │              │
│           │   │   $19/mo     │  │   $49/mo     │  │   $99/mo      │              │
│           │   │ 14-day trial  │  │ 14-day trial │  │ 14-day trial  │              │
│           │   └──────────────┘  └──────────────┘  └──────────────┘              │
│           │                                                                     │
│  9:35 AM  │ Sarah selects "Growth" plan (needs marketing features)           │
│  9:36 AM  │ ✓ Subscription created (trialing until Jan 29)                    │
│  9:37 AM  │ ✓ StoreMembership created (Sarah = Store Owner)                   │
│  9:38 AM  │ Sarah is redirected to her dashboard!                             │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 1: First Exploration
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  9:40 AM  │ Dashboard shows:                                                    │
│           │   - Welcome message                                                 │
│           │   - Quick setup checklist                                           │
│           │   - Plan info: "Growth Plan - Trial"                                │
│           │   - Team: "1 of 10 users used"                                     │
│           │                                                                     │
│  9:45 AM  │ Sarah tries to access different sections:                          │
│           │                                                                     │
│           │   ✓ Customers (allowed - has customers.view)                        │
│           │   ✓ Products (allowed - has products.view)                          │
│           │   ✓ Orders (allowed - has orders.view)                              │
│           │   ✓ Campaigns (allowed - plan has marketing_campaigns)             │
│           │   ✓ Reports (allowed - plan has advanced_reports)                   │
│           │   ✗ SSO Settings (denied - plan doesn't have sso feature)          │
│           │                                                                     │
│  9:50 AM  │ Notification: "SSO requires Enterprise plan"                        │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 2: Team Building
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  10:00 AM │ Sarah invites her team:                                            │
│           │                                                                     │
│           │   1. Mike Chen    → Role: Sales Agent                               │
│           │   2. Lisa Park    → Role: Inventory Manager                         │
│           │   3. Tom Davis    → Role: Marketing Executive                       │
│           │                                                                     │
│  10:05 AM │ Emails sent to team members                                        │
│  10:15 AM │ Mike Chen accepts invitation                                       │
│  10:16 AM │ ✓ Mike's StoreMembership created (active, role=Sales Agent)         │
│  10:20 AM │ Lisa accepts                                                         │
│  10:25 AM │ Tom accepts                                                          │
│           │                                                                     │
│  10:26 AM │ Dashboard now shows: "4 of 10 users used"                           │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 5: Custom Permissions
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  2:00 PM  │ Sarah needs Mike to export customer data temporarily               │
│           │                                                                     │
│  2:05 PM  │ She creates a UserPermissionOverride:                              │
│           │   - User: Mike Chen                                                │
│           │   - Permission: customers.export                                    │
│           │   - Is Granted: Yes                                                │
│           │   - Expires: Tomorrow at midnight                                  │
│           │   - Reason: "Monthly report export"                                │
│           │                                                                     │
│  2:06 PM  │ ✓ Mike can now export customers (for 24 hours only)                │
│           │   Note: Mike's normal role (Sales Agent) doesn't allow this         │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 15: Trial Ending
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  9:00 AM  │ Sarah receives email: "Your trial ends in 1 day"                    │
│           │                                                                     │
│  9:30 AM  │ She logs in and sees subscription banner:                          │
│           │   "Your trial expires tomorrow. Subscribe to keep using..."        │
│           │                                                                     │
│  9:35 AM  │ Sarah clicks "Subscribe"                                            │
│  9:36 AM  │ Payment page shows:                                                 │
│           │   - Growth Plan: $49/month                                         │
│           │   - Billing cycle: Monthly                                         │
│           │   - Card: •••• •••• •••• 4242                                      │
│           │                                                                     │
│  9:38 AM  │ Sarah confirms payment                                             │
│  9:39 AM  │ Stripe processes payment → SUCCESS                                 │
│  9:40 AM  │ ✓ Subscription status: trialing → active                           │
│  9:40 AM  │ ✓ Period set: Jan 15 - Feb 15                                      │
│  9:41 AM  │ Confirmation email sent                                           │
│  9:42 AM  │ Banner disappears: "All features active!"                          │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 30: Team Growth
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  3:00 PM  │ Sarah hires 3 more team members                                     │
│           │   - Jenna: Customer Support                                        │
│           │   - Alex: Accountant                                               │
│           │   - Ryan: Sales Agent                                               │
│           │                                                                     │
│  3:05 PM  │ She tries to add Alex but gets:                                     │
│           │   "Plan limit reached: Growth plan allows 10 users maximum"        │
│           │                                                                     │
│  3:06 PM  │ Current count: 10 users (at limit)                                  │
│           │                                                                     │
│  3:10 PM  │ Sarah considers options:                                            │
│           │   1. Remove a team member                                          │
│           │   2. Upgrade to Professional plan (25 users)                        │
│           │                                                                     │
│  3:15 PM  │ She upgrades to Professional plan                                   │
│  3:16 PM  │ ✓ Plan changed: Growth → Professional                             │
│  3:16 PM  │ ✓ New limit: 25 users                                              │
│  3:17 AM  │ Sarah adds Alex, Jenna, and Ryan successfully                     │
│           │                                                                     │
│  3:18 PM  │ Dashboard shows: "13 of 25 users used"                              │
│           │   Bonus: Now has access to multi-warehouse, API, and integrations  │
└─────────────────────────────────────────────────────────────────────────────────┘

DAY 60: Custom Role Creation
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  11:00 AM │ Sarah needs a specialized role: "Fulfillment Manager"              │
│           │   - Should manage orders and warehouses                            │
│           │   - Should NOT access financial reports                            │
│           │                                                                     │
│  11:05 AM │ She creates a custom role:                                         │
│           │   1. Clones "Manager" role                                         │
│           │   2. Renames to "Fulfillment Manager"                              │
│           │   3. Removes permissions:                                          │
│           │      - reports.view                                                │
│           │      - reports.create                                              │
│           │      - settings.update (billing section)                          │
│           │   4. Keeps permissions:                                            │
│           │      - orders.* (all)                                             │
│           │      - warehouses.* (all)                                         │
│           │      - inventory.* (all)                                           │
│           │      - customers.view (for shipping info)                          │
│           │                                                                     │
│  11:10 AM │ ✓ Custom role created                                              │
│  11:12 AM │ Sarah assigns role to existing staff member, Ryan                  │
│  11:13 AM │ ✓ Ryan's permissions updated immediately                            │
│           │   Note: Cache automatically invalidated                             │
└─────────────────────────────────────────────────────────────────────────────────┘

ONGOING: Daily Operations
─────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Every day│ Sarah and team work in the system:                                  │
│           │                                                                     │
│           │   Mike (Sales Agent):                                              │
│           │   ✓ Can view customers                                             │
│           │   ✓ Can create orders                                              │
│           │   ✗ Cannot delete orders                                           │
│           │   ✗ Cannot access reports                                           │
│           │                                                                     │
│           │   Lisa (Inventory Manager):                                        │
│           │   ✓ Can manage products                                            │
│           │   ✓ Can update stock levels                                        │
│           │   ✓ Can manage warehouses                                          │
│           │   ✗ Cannot access campaigns                                        │
│           │                                                                     │
│           │   Tom (Marketing Exec):                                            │
│           │   ✓ Can create campaigns                                           │
│           │   ✓ Can send emails                                                │
│           │   ✓ Can view campaign reports                                      │
│           │   ✗ Cannot modify products                                          │
│           │                                                                     │
│           │   Ryan (Fulfillment Manager):                                      │
│           │   ✓ Can manage orders                                              │
│           │   ✓ Can manage warehouses                                          │
│           │   ✓ Can view customers (for shipping)                               │
│           │   ✗ Cannot access reports                                           │
│           │   ✗ Cannot access billing settings                                  │
│           │                                                                     │
│  All actions are logged in AuditLog for security                               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Customer Quick Start Guide

### What You Need to Do (From Starting)

#### **STEP 1: Create Your Account**

```
Go to: app.example.com/signup

Required information:
├── Full name
├── Email address
└── Password (minimum 8 characters)

After signup:
├── Check your email for verification link
└── Click the link to verify your account
```

#### **STEP 2: Create Your First Store**

```
After verification, you'll see "Create Store" page.

Fill in:
├── Store name (e.g., "My Awesome Store")
├── Business type (retail, wholesale, service, etc.)
├── Phone number
└── Country/Region

Click "Create Store"
→ Your store is ready instantly!
→ You'll start with a 14-day free trial
```

#### **STEP 3: Choose Your Plan**

```
You'll see 4 plan options:

┌──────────────┬──────────────┬──────────────┬──────────────┐
│   STARTER    │   GROWTH     │PROFESSIONAL  │ ENTERPRISE   │
│    $19/mo    │    $49/mo    │    $99/mo    │   $299/mo    │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ Best for:    │ Best for:    │ Best for:    │ Best for:    │
│ Small teams  │ Growing      │ Established  │ Large        │
│              │ businesses   │ businesses   │ operations   │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ 3 users      │ 10 users     │ 25 users     │ Unlimited    │
│ 1 store      │ 3 stores     │ 10 stores    │ Unlimited    │
│ 500 products │ 5,000 prods  │ 25,000 prods │ Unlimited    │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ Basic        │ + Marketing  │ + Multi-     │ + SSO       │
│ features     │   campaigns  │   warehouse  │ + Priority  │
│              │ + Inventory  │ + API        │   support   │
│              │ + Team mgmt  │ + Integrations│           │
└──────────────┴──────────────┴──────────────┴──────────────┘

All plans include:
✓ 14-day free trial
✓ Customer management
✓ Order processing
✓ Basic reports

Select the plan that fits your needs.
You can change it later!
```

#### **STEP 4: Explore Your Dashboard**

```
First time dashboard shows:

┌────────────────────────────────────────────┐
│  Welcome to Your Store!                    │
│                                            │
│  Quick Start:                              │
│  ┌──────────────────────────────────────┐ │
│  │ ☐ Add your first customer             │ │
│  │ ☐ Create your first product           │ │
│  │ ☐ Set up your first order             │ │
│  │ ☐ Run your first report               │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  Your Plan: Growth (Trial - 12 days left) │
│  Team: 1 of 10 users                      │
└────────────────────────────────────────────┘
```

#### **STEP 5: Invite Your Team (Optional)**

```
Go to: Settings → Team → Invite Member

For each person:
├── Enter their email
├── Select their role:
│   ├── Store Owner (full access)
│   ├── Admin (all except ownership)
│   ├── Manager (daily operations)
│   ├── Sales Agent (sales only)
│   ├── Customer Support (customer service)
│   ├── Inventory Manager (stock only)
│   ├── Marketing Exec (campaigns only)
│   ├── Accountant (reports only)
│   └── Viewer (read-only)
└── Click "Send Invitation"

They'll receive an email with signup link
```

#### **STEP 6: Start Using the System**

```
Based on your role, you can:

As Store Owner, you can do EVERYTHING:
├── Manage customers (add, edit, delete)
├── Manage products (add, edit, delete)
├── Process orders
├── Run marketing campaigns
├── View all reports
├── Manage team
├── Customize settings
└── Upgrade/downgrade plan

Other roles have limited access.
See "What Each Role Can Do" section below.
```

### What Each Role Can Do

#### **Store Owner (You)**
```
✓ Everything
✓ Can transfer ownership
✓ Can cancel subscription
✓ Can delete store
```

#### **Admin**
```
✓ Manage customers
✓ Manage products
✓ Process orders
✓ Run campaigns
✓ View reports
✓ Manage team (except owner)
✓ Update settings

✗ Cannot transfer ownership
✗ Cannot delete store
✗ Cannot cancel subscription
```

#### **Manager**
```
✓ View and create customers
✓ View and create products
✓ Process orders
✓ View basic reports
✓ Manage campaigns

✗ Cannot manage team
✗ Cannot access billing settings
✗ Cannot delete store
```

#### **Sales Agent**
```
✓ View customers
✓ Create orders
✓ View own orders
✓ Update order status

✗ Cannot delete orders
✗ Cannot access reports
✗ Cannot manage products
✗ Cannot manage team
```

#### **Customer Support**
```
✓ View customers
✓ View orders
✓ Reply to customers

✗ Cannot delete customers
✗ Cannot modify products
✗ Cannot access financial reports
```

#### **Viewer**
```
✓ View customers
✓ View products
✓ View orders
✓ View basic reports

✗ Cannot create anything
✗ Cannot edit anything
✗ Cannot delete anything
✗ Cannot access settings
```

### What Features Each Plan Has

```
┌──────────────────┬─────────┬─────────┬────────────┬───────────┐
│ Feature          │ Starter │ Growth  │Professional│ Enterprise │
├──────────────────┼─────────┼─────────┼────────────┼───────────┤
│ Customers        │    ✓    │    ✓    │     ✓      │     ✓     │
│ Basic Reports    │    ✓    │    ✓    │     ✓      │     ✓     │
│ Inventory        │    ✗    │    ✓    │     ✓      │     ✓     │
│ Marketing        │    ✗    │    ✓    │     ✓      │     ✓     │
│ Advanced Reports │    ✗    │    ✓    │     ✓      │     ✓     │
│ Team Management  │    ✗    │    ✓    │     ✓      │     ✓     │
│ Multi-Warehouse │    ✗    │    ✗    │     ✓      │     ✓     │
│ API Access       │    ✗    │    ✗    │     ✓      │     ✓     │
│ Integrations     │    ✗    │    ✗    │     ✓      │     ✓     │
│ SSO              │    ✗    │    ✗    │     ✗      │     ✓     │
│ Audit Export     │    ✗    │    ✗    │     ✗      │     ✓     │
└──────────────────┴─────────┴─────────┴────────────┴───────────┘

Key:
✓ = Included
✗ = Not included (requires upgrade)
```

### Common Questions

**Q: Can I change my plan later?**
A: Yes! You can upgrade or downgrade anytime from Settings → Subscription

**Q: What happens when my trial ends?**
A: Your store will be locked until you subscribe. You'll receive reminder emails 3 days, 1 day, and on the day.

**Q: Can I have multiple stores?**
A: Depends on your plan:
- Starter: 1 store
- Growth: 3 stores
- Professional: 10 stores
- Enterprise: Unlimited

**Q: What if I need more users than my plan allows?**
A: Upgrade to a higher plan or remove inactive users.

**Q: Can I create custom roles?**
A: Yes! From Settings → Roles → Create Custom Role. You can clone existing roles and modify permissions.

**Q: How do I give someone temporary access?**
A: Create a UserPermissionOverride from their profile page with an expiration date.

**Q: What happens to my data if I cancel?**
A: Your data is retained for 30 days. After that, it's permanently deleted.

---

## 7. How Permissions Work (Simplified)

### The 5-Layer Permission Check

When you try to do ANYTHING in the system, it goes through 5 checks:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          YOU WANT TO CREATE AN ORDER                             │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  CHECK 1: Are you logged in?                                                    │
│                                                                                 │
│  ┌──────────┐      ┌──────────┐                                                │
│  │ NO ✗     │      │ YES ✓    │                                                │
│  └────┬─────┘      └────┬─────┘                                                │
│       │                 │                                                        │
│       ▼                 ▼                                                        │
│  "Login first"    Continue to next check                                       │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  CHECK 2: Are you a superuser? (System Admin)                                   │
│                                                                                 │
│  ┌──────────┐      ┌──────────┐                                                │
│  │ YES ✓    │      │ NO ✗     │                                                │
│  └────┬─────┘      └────┬─────┘                                                │
│       │                 │                                                        │
│       ▼                 ▼                                                        │
│  ACCESS GRANTED    Continue to next check                                      │
│  (Admins can do                                                              │
│   everything)                                                                │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  CHECK 3: Does your store's plan allow this feature?                            │
│                                                                                 │
│  System checks:                                                                 │
│  - Does your store have an active subscription?                                 │
│  - Does your plan include "orders" feature?                                     │
│                                                                                 │
│  ┌──────────┐      ┌──────────┐                                                │
│  │ NO ✗     │      │ YES ✓    │                                                │
│  └────┬─────┘      └────┬─────┘                                                │
│       │                 │                                                        │
│       ▼                 ▼                                                        │
│  "Upgrade your    Continue to next check                                       │
│   plan to access                                                              │
│   this feature"                                                              │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  CHECK 4: Are you a member of this store?                                       │
│                                                                                 │
│  System checks:                                                                 │
│  - Do you have an active StoreMembership for this store?                        │
│  - Is your membership not expired?                                               │
│                                                                                 │
│  ┌──────────┐      ┌──────────┐                                                │
│  │ NO ✗     │      │ YES ✓    │                                                │
│  └────┬─────┘      └────┬─────┘                                                │
│       │                 │                                                        │
│       ▼                 ▼                                                        │
│  "You don't have    Continue to next check                                       │
│   access to this                                                               │
│   store"                                                                     │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  CHECK 5: Does your role allow this specific permission?                         │
│                                                                                 │
│  System checks:                                                                 │
│  - What roles do you have in this store?                                       │
│  - What permissions do those roles grant?                                       │
│  - What permissions do those roles deny?                                        │
│  - Any user-specific overrides?                                                 │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ Grant Permission Example:                                               │   │
│  │                                                                          │   │
│  │ Role: Sales Agent                                                       │   │
│  │ └── orders.create: GRANT ✓                                              │   │
│  │                                                                          │   │
│  │ Result: You CAN create orders                                           │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ Deny Permission Example:                                                │   │
│  │                                                                          │   │
│  │ Role: Sales Agent                                                       │   │
│  │ └── orders.delete: DENY ✗                                               │   │
│  │                                                                          │   │
│  │ Result: You CANNOT delete orders                                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  CHECK 6: (Optional) Object-level check                                         │
│                                                                                 │
│  For specific objects, additional checks:                                       │
│  - Can you modify THIS SPECIFIC order?                                         │
│  - Do you own this customer record?                                            │
│                                                                                 │
│  Example:                                                                      │
│  - Sales Agent can only modify their own orders                                │
│  - Manager can modify any order                                                │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          FINAL RESULT                                            │
│                                                                                 │
│  ┌─────────────────────┐    ┌─────────────────────┐                            │
│  │     ACCESS GRANTED  │    │    ACCESS DENIED     │                            │
│  │                     │    │                     │                            │
│  │  You can proceed!   │    │  Reason shown:      │                            │
│  │                     │    │  "You don't have     │                            │
│  │                     │    │   permission to      │                            │
│  │                     │    │   delete orders"     │                            │
│  └─────────────────────┘    └─────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### The Golden Rule

**DENY always beats GRANT**

```
Scenario:
- Your role grants you "orders.delete"
- But someone set a DENY override on you for "orders.delete"
- Result: You CANNOT delete orders (DENY wins)

This is for security:
- Prevents privilege escalation
- Allows emergency access revocation
- Ensures safety overrides
```

### How the System Remembers

The system uses **caching** to be fast:

```
First time you log in:
├── System calculates all your permissions
├── Stores them in cache (temporary memory)
└── Next checks are super fast!

When something changes:
├── Your role changes → Cache cleared
├── Your membership changes → Cache cleared
├── An override is added → Cache cleared
└── Next check recalculates fresh permissions

This ensures:
- Fast performance (doesn't check database every time)
- Accurate permissions (always up-to-date)
- Security (changes take effect immediately)
```

### What Gets Logged

Every permission change is logged:

```
AuditLog records:
├── WHO made the change
├── WHAT changed
├── BEFORE state
├── AFTER state
├── WHEN it happened
├── WHERE from (IP address)
└── Request ID (for tracing)

Example:
├── Action: membership.create
├── Actor: sarah@bloomflow.com
├── Target: Mike Chen's membership
├── Before: null
├── After: {role: "Sales Agent", active: true}
├── IP: 192.168.1.100
└── Time: 2024-01-15 10:30:00
```

---

## Summary

### Key Points to Remember

1. **Users** belong to **Stores** through **Memberships** with **Roles**
2. **Roles** have **Permissions** that GRANT or DENY abilities
3. **Stores** have **Subscriptions** to **Plans** with **Features**
4. **DENY** always beats **GRANT** (security first)
5. **Superusers** bypass all checks (use carefully)
6. Everything is **logged** in **AuditLog**
7. **Caching** makes checks fast and accurate

### The Complete Picture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   YOU ───> MEMBERSHIP ───> ROLE ───> PERMISSIONS ───> ACTION ALLOWED/DENIED    │
│     │           │            │          │                                        │
│     │           │            │          └─ Plan features must be included       │
│     │           │            └─ Role defines what you can do                   │
│     │           └─ Must be active and not expired                               │
│     └─ Must be authenticated                                                     │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Need Help?

- **Technical questions**: See [role-and-permission-system.md](role-and-permission-system.md)
- **Quick reference**: See [rbac-quick-reference.md](rbac-quick-reference.md)
- **Visual diagrams**: See [permission-flow-diagram.md](permission-flow-diagram.md)

---

**Last Updated:** January 18, 2026
