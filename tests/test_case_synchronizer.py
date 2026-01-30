"""Quick verification script for CaseJsonSynchronizer (Phase 1 - P1)."""
import json
from pathlib import Path

from webqa_agent.executor.gen.utils.case_synchronizer import \
    CaseJsonSynchronizer

print('=' * 60)
print('CaseJsonSynchronizer 验证测试')
print('=' * 60)

# 准备测试目录
test_dir = Path('/tmp/webqa-test-sync')
test_dir.mkdir(exist_ok=True)
cases_json_path = test_dir / 'cases.json'

print(f'\n✓ 测试目录: {test_dir}')
print(f'✓ cases.json 路径: {cases_json_path}\n')

# 模拟原始 test_cases (planning 阶段生成)
test_cases = [
    {
        'case_id': 'case_1',
        'name': 'Test_Login',
        'status': 'pending',  # 初始状态
        'objective': '测试登录功能',
        'steps': [{'action': 'click', 'target': 'login_button'}],
    },
    {
        'case_id': 'case_2',
        'name': 'Test_Signup',
        'status': 'pending',  # 初始状态
        'objective': '测试注册功能',
        'steps': [{'action': 'fill', 'target': 'email_input'}],
    },
    {
        'case_id': 'case_3',
        'name': 'Test_Navigation',
        'status': 'pending',  # 初始状态
        'objective': '测试导航功能',
        'steps': [{'action': 'click', 'target': 'nav_link'}],
    },
]

# 保存初始 cases.json
with open(cases_json_path, 'w', encoding='utf-8') as f:
    json.dump(test_cases, f, ensure_ascii=False, indent=4)

print('=== 步骤 1: 初始 cases.json (所有状态为 pending) ===')
for case in test_cases:
    print(f"  {case['case_id']}: {case['name']} - status: {case['status']}")

# 模拟 recorded_cases (execution 阶段生成)
recorded_cases = [
    {
        'case_id': 'case_1',
        'status': 'passed',  # ✅ 执行成功
        'start_time': '2026-01-30T10:00:00',
        'end_time': '2026-01-30T10:00:15',
        'duration': 15.2,
        'steps': [
            {
                'description': 'Click login button',
                'status': 'passed',
                'timestamp': '2026-01-30T10:00:10',
            }
        ],
    },
    {
        'case_id': 'case_2',
        'status': 'failed',  # ❌ 执行失败
        'start_time': '2026-01-30T10:00:20',
        'end_time': '2026-01-30T10:00:35',
        'duration': 15.8,
        'error': 'Element not found',
        'failure_type': 'element_not_found',
        'steps': [
            {
                'description': 'Fill email input',
                'status': 'failed',
                'timestamp': '2026-01-30T10:00:30',
            }
        ],
    },
    {
        'case_id': 'case_3',
        'status': 'warning',  # ⚠️ 执行有警告
        'start_time': '2026-01-30T10:00:40',
        'end_time': '2026-01-30T10:00:55',
        'duration': 15.5,
        'steps': [
            {
                'description': 'Click navigation link',
                'status': 'passed',
                'timestamp': '2026-01-30T10:00:45',
            },
            {
                'description': 'Verify page title',
                'status': 'warning',
                'timestamp': '2026-01-30T10:00:50',
            },
        ],
    },
]

print('\n=== 步骤 2: Recorded Execution Results ===')
for case in recorded_cases:
    print(
        f"  {case['case_id']}: status={case['status']}, "
        f"duration={case['duration']}s, steps={len(case['steps'])}"
    )

# 执行同步
print('\n=== 步骤 3: 执行同步 ===')
synchronizer = CaseJsonSynchronizer(cases_json_path)
synchronizer.sync_cases(test_cases, recorded_cases)
print('✓ 同步完成')

# 读取同步后的 cases.json
with open(cases_json_path, 'r', encoding='utf-8') as f:
    synced_cases = json.load(f)

print('\n=== 步骤 4: 同步后的 cases.json ===')
for case in synced_cases:
    print(f"  {case['case_id']}: {case['name']}")
    print(f"    - status: {case['status']}")
    print(f"    - has completed_steps: {'completed_steps' in case}")
    print(f"    - has start_time: {'start_time' in case}")
    print(f"    - has duration: {'duration' in case}")
    if case.get('status') == 'failed':
        print(f"    - error: {case.get('error')}")
        print(f"    - failure_type: {case.get('failure_type')}")

# 验证结果
print('\n' + '=' * 60)
print('验证结果')
print('=' * 60)

passed = 0
failed = 0
tests = []


def verify(condition, message):
    global passed, failed
    tests.append({'message': message, 'result': '✅' if condition else '❌'})
    if condition:
        passed += 1
        print(f'✅ {message}')
    else:
        failed += 1
        print(f'❌ {message}')


# 验证 case_1 (passed)
case_1 = synced_cases[0]
verify(case_1['status'] == 'passed', "Case 1 status 更新为 'passed'")
verify('completed_steps' in case_1, 'Case 1 包含 completed_steps')
verify('start_time' in case_1, 'Case 1 包含 start_time')
verify('duration' in case_1, 'Case 1 包含 duration')
verify(case_1['duration'] == 15.2, 'Case 1 duration 正确 (15.2s)')

# 验证 case_2 (failed)
case_2 = synced_cases[1]
verify(case_2['status'] == 'failed', "Case 2 status 更新为 'failed'")
verify(case_2.get('error') == 'Element not found', 'Case 2 包含 error 信息')
verify(
    case_2.get('failure_type') == 'element_not_found', 'Case 2 包含 failure_type'
)
verify('completed_steps' in case_2, 'Case 2 包含 completed_steps')

# 验证 case_3 (warning)
case_3 = synced_cases[2]
verify(case_3['status'] == 'warning', "Case 3 status 更新为 'warning'")
verify('completed_steps' in case_3, 'Case 3 包含 completed_steps')
verify(len(case_3['completed_steps']) == 2, 'Case 3 包含 2 个 completed_steps')

# 验证 completed_steps 结构
verify(
    case_1['completed_steps'][0].get('description') == 'Click login button',
    'Case 1 completed_steps[0] description 正确',
)
verify(
    case_1['completed_steps'][0].get('status') == 'passed',
    'Case 1 completed_steps[0] status 正确',
)

# 总结
print('\n' + '=' * 60)
print('测试总结')
print('=' * 60)
print(f'总计: {passed + failed} 个验证')
print(f'✅ 通过: {passed} 个')
print(f'❌ 失败: {failed} 个')

if failed == 0:
    print('\n🎉 所有验证通过！CaseJsonSynchronizer 工作正常。')
    print('\n最终 cases.json 已保存到:')
    print(f'  {cases_json_path}')
    print('\n你可以查看该文件验证同步结果。')
    exit(0)
else:
    print(f'\n⚠️  有 {failed} 个验证失败，需要检查。')
    exit(1)
