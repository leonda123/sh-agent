import sys
sys.path.insert(0, 'd:\\work\\sh-agent')

from app.core.agent_manager import AgentManager

manager = AgentManager()
agents = manager.list_agents()

print(f'已注册智能体数量: {len(agents)}')
for a in agents:
    if a["id"] == "doc_toc_structure_check":
        print(f'=== {a["id"]}: {a["name"]} ===')
        print(f'描述: {a["description"]}')
        print(f'分类目录: {a["category_folder"]}')
        print(f'分类名称: {a["category_name"]}')
        print(f'最少文件数: {a["min_file_count"]}')
        print(f'最多文件数: {a["max_file_count"]}')
        print(f'支持多文件: {a["accepts_multiple_files"]}')
        print()
        print('检查项:')
        for item in a["checklist_items"]:
            print(f'  - {item["item_no"]}. {item["content"]}')
        print()
        print('阶段定义:')
        for phase in a["phase_definitions"]:
            print(f'  - {phase["id"]}: {phase["label"]}')
        print()
        print('阶段任务要求:')
        for phase_id, count in a["phase_task_requirements"].items():
            print(f'  - {phase_id}: {count} 个任务')
        print()
        print('角色阶段映射:')
        for role, phase_id in a["role_phase_map"].items():
            print(f'  - {role} -> {phase_id}')
        print()
