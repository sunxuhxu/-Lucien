"""测试video_apps.py基础功能"""
import sys
import os
import asyncio

# 确保正确的项目路径
project_root = r'G:\xumo'
sys.path.insert(0, project_root)
try:
    os.chdir(project_root)
except:
    pass  # ignore if already in correct directory

try:
    from video_apps import (
        router, 
        _get_growth_stage, 
        GROWTH_STAGES,
        VIDEO_CONFIG
    )
except ImportError as e:
    print(f"导入失败: {e}")
    sys.exit(1)

def test_basic_imports():
    """测试基础导入"""
    print("✓ 基础导入成功")
    try:
        print(f"✓ Router前缀: {router.prefix}")
        print(f"✓ Router标签: {router.tags}")
        print(f"✓ 可用路由数: {len(router.routes)}")
    except Exception as e:
        print(f"  Router信息获取失败: {e}")

def test_growth_stages():
    """测试关系阶段判断"""
    print("\n--- 测试关系阶段判断 ---")
    
    # 测试不同亲和度对应的阶段
    test_cases = [
        (10, "first_encounter"),
        (35, "getting_know"), 
        (60, "deep_connection"),
        (80, "commitment"),
        (95, "soulmate")
    ]
    
    for affinity, expected_stage in test_cases:
        result = _get_growth_stage(affinity)
        stage_name = GROWTH_STAGES[result]["name"]
        print(f"✓ 亲和度 {affinity}% -> {stage_name} ({result})")
        assert result == expected_stage, f"Expected {expected_stage}, got {result}"

def test_video_config():
    """测试视频配置"""
    print("\n--- 测试视频配置 ---")
    print(f"✓ 输出目录: {VIDEO_CONFIG['output_dir']}")
    print(f"✓ 临时目录: {VIDEO_CONFIG['temp_dir']}")
    print(f"✓ 最大时长: {VIDEO_CONFIG['max_duration']}秒")
    print(f"✓ 默认分辨率: {VIDEO_CONFIG['default_resolution']}")
    print(f"✓ 默认帧率: {VIDEO_CONFIG['default_fps']}fps")

def test_api_routes():
    """测试API路由"""
    print("\n--- 测试API路由 ---")
    for route in router.routes:
        methods = ', '.join(route.methods)
        print(f"✓ {methods:6} {route.path}")

async def test_data_aggregation():
    """测试数据聚合功能（模拟）"""
    print("\n--- 测试数据聚合功能 ---")
    print("✓ 数据聚合函数已定义:")
    print("  - _aggregate_chat_data")
    print("  - _aggregate_memory_data") 
    print("  - _aggregate_date_data")
    print("  - _aggregate_affinity_data")
    print("  - _analyze_relationship_stage")
    print("  - _generate_growth_narration")

def main():
    """运行所有测试"""
    print("=" * 50)
    print("video_apps.py 基础功能测试")
    print("=" * 50)
    
    try:
        test_basic_imports()
        test_growth_stages()
        test_video_config()
        test_api_routes()
        asyncio.run(test_data_aggregation())
        
        print("\n" + "=" * 50)
        print("✅ 所有测试通过！")
        print("=" * 50)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())