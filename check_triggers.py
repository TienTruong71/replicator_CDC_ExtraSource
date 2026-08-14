import sys, os
sys.path.insert(0, 'replicator/src')
from db_utils import connect_db
from dotenv import load_dotenv
load_dotenv()

print('=== KIỂM TRA CDC TRIGGERS ===')
conn = connect_db('KINGDOM', target=False)
cursor = conn.cursor()

try:
    cursor.execute("SELECT name FROM sys.triggers WHERE name LIKE 'trig_cdc_%'")
    triggers = cursor.fetchall()
    print(f'Triggers found: {len(triggers)}')
    for trigger in triggers:
        print(f'  - {trigger[0]}')
except Exception as e:
    print(f'Error: {e}')
    
conn.close()
