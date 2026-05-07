"""
ProVisionGuard AI — License Key Generator
==========================================
This tool is for the SELLER (you) to generate license keys for customers.
Customers cannot generate their own keys.

Usage:
    python keygen.py                    (interactive mode)
    python keygen.py --list             (list all generated keys)
    python keygen.py --revoke KEY       (revoke a key)

Plans:
    TRIAL       — 7 days  (free demo)
    BASIC       — 1 cam, no face recog, Rs.12,000/yr
    PRO         — 4 cams, full features, Rs.26,000/yr
    ENTERPRISE  — unlimited, custom, negotiable
"""

import hashlib, hmac, json, os, argparse
from datetime import datetime, timedelta

SECRET       = 'PVG-SECRET-2026-SHEIK'
KEYS_LOG     = 'generated_keys.json'

PLANS = {
    'TRIAL':      {'cameras':1,  'days':7,   'price':'FREE',         'faces':False},
    'BASIC':      {'cameras':1,  'days':365, 'price':'Rs.12,000/yr', 'faces':False},
    'PRO':        {'cameras':4,  'days':365, 'price':'Rs.26,000/yr', 'faces':True},
    'ENTERPRISE': {'cameras':99, 'days':730, 'price':'Custom',       'faces':True},
}

def generate_key(plan, customer, days=None):
    plan = plan.upper()
    if plan not in PLANS:
        print(f"Unknown plan: {plan}. Choose from: {list(PLANS.keys())}")
        return None
    d     = days or PLANS[plan]['days']
    expiry= (datetime.now() + timedelta(days=d)).strftime('%Y-%m-%d')
    payload = f"{plan}|{customer}|{expiry}"
    sig   = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16].upper()
    key   = f"PVG-{plan[:3]}-{sig[:4]}-{sig[4:8]}-{sig[8:12]}-{sig[12:16]}"
    record = {
        'key':       key,
        'plan':      plan,
        'customer':  customer,
        'expiry':    expiry,
        'days':      d,
        'price':     PLANS[plan]['price'],
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'revoked':   False,
    }
    # Save to log
    log = load_log()
    log.append(record)
    save_log(log)
    return record

def load_log():
    if os.path.exists(KEYS_LOG):
        with open(KEYS_LOG) as f:
            return json.load(f)
    return []

def save_log(log):
    with open(KEYS_LOG, 'w') as f:
        json.dump(log, f, indent=2)

def list_keys():
    log = load_log()
    if not log:
        print("No keys generated yet.")
        return
    print(f"\n{'='*80}")
    print(f"{'KEY':<35} {'PLAN':<12} {'CUSTOMER':<20} {'EXPIRY':<12} {'STATUS'}")
    print(f"{'='*80}")
    for r in log:
        status = 'REVOKED' if r.get('revoked') else 'ACTIVE'
        exp    = r['expiry']
        expired= datetime.strptime(exp,'%Y-%m-%d') < datetime.now()
        if expired and not r.get('revoked'): status = 'EXPIRED'
        color  = '\033[91m' if status!='ACTIVE' else '\033[92m'
        reset  = '\033[0m'
        print(f"{r['key']:<35} {r['plan']:<12} {r['customer'][:18]:<20} {exp:<12} {color}{status}{reset}")
    print(f"{'='*80}")
    print(f"Total: {len(log)} keys\n")

def revoke_key(key):
    log = load_log()
    found = False
    for r in log:
        if r['key'].upper() == key.upper():
            r['revoked'] = True
            found = True
            print(f"Key revoked: {key}")
            break
    if not found:
        print(f"Key not found: {key}")
    save_log(log)

def interactive():
    print("\n" + "="*50)
    print("  ProVisionGuard AI — License Key Generator")
    print("="*50)
    print("\nPlans available:")
    for p, info in PLANS.items():
        print(f"  {p:<12} {info['price']:<18} {info['days']}d  {info['cameras']} cam(s)")

    print("\n")
    plan = input("Enter plan (TRIAL/BASIC/PRO/ENTERPRISE): ").strip().upper()
    if plan not in PLANS:
        print("Invalid plan!"); return

    customer = input("Enter customer/company name: ").strip()
    if not customer:
        print("Customer name required!"); return

    custom_days = input(f"Custom days? (Enter for default {PLANS[plan]['days']}d): ").strip()
    days = int(custom_days) if custom_days.isdigit() else None

    record = generate_key(plan, customer, days)
    if not record: return

    print("\n" + "="*50)
    print("  LICENSE KEY GENERATED")
    print("="*50)
    print(f"  Key      : {record['key']}")
    print(f"  Plan     : {record['plan']}")
    print(f"  Customer : {record['customer']}")
    print(f"  Expiry   : {record['expiry']} ({record['days']} days)")
    print(f"  Price    : {record['price']}")
    print("="*50)
    print("\n  Send this key to your customer.")
    print("  They enter it at: http://localhost:5000/setup")
    print()

    # Save to text file for easy sharing
    out = f"pvg_key_{customer.replace(' ','_')}_{record['plan']}.txt"
    with open(out, 'w') as f:
        f.write(f"ProVisionGuard AI License Key\n")
        f.write(f"{'='*40}\n")
        f.write(f"Customer : {record['customer']}\n")
        f.write(f"Plan     : {record['plan']}\n")
        f.write(f"Key      : {record['key']}\n")
        f.write(f"Expiry   : {record['expiry']}\n")
        f.write(f"Price    : {record['price']}\n")
        f.write(f"{'='*40}\n")
        f.write(f"\nActivation:\n")
        f.write(f"1. Open http://localhost:5000/setup\n")
        f.write(f"2. Login as admin\n")
        f.write(f"3. Enter key in License Management section\n")
        f.write(f"4. Click ACTIVATE LICENSE\n")
    print(f"  Key saved to: {out}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--list',   action='store_true')
    parser.add_argument('--revoke', type=str, default='')
    parser.add_argument('--plan',   type=str, default='')
    parser.add_argument('--customer',type=str,default='')
    parser.add_argument('--days',   type=int, default=0)
    args = parser.parse_args()

    if args.list:
        list_keys()
    elif args.revoke:
        revoke_key(args.revoke)
    elif args.plan and args.customer:
        r = generate_key(args.plan, args.customer, args.days or None)
        if r:
            print(f"\nKey: {r['key']}")
            print(f"Expiry: {r['expiry']}")
    else:
        interactive()