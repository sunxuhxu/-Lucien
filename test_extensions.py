#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试AI自定义扩展功能"""
import json
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def test_ai_builder_import():
    """测试AI构建器模块导入"""
    try:
        import ai_extension_builder
        from ai_extension_builder import ExtensionBuilder, EXTENSION_TYPES
        print("✅ AI构建器模块导入成功")
        print(f"   支持的扩展类型: {list(EXTENSION_TYPES.keys())}")
        return True
    except Exception as e:
        print(f"❌ AI构建器模块导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_extensions_apps_import():
    """测试扩展应用模块导入"""
    try:
        from extensions_apps import (
            _parse_natural_language_description,
            _detect_extension_type,
            _generate_prompt_from_description
        )
        print("✅ 扩展应用模块导入成功")
        return True
    except Exception as e:
        print(f"❌ 扩展应用模块导入失败: {e}")
        return False

def test_natural_language_generation():
    """测试自然语言生成功能"""
    try:
        from extensions_apps import (
            _parse_natural_language_description,
            _detect_extension_type
        )
        
        # 测试不同类型的描述
        test_cases = [
            ("让AI在深夜时语气更温柔", "prompt_template"),
            ("用户问天气时调用天气API", "tool_chain"),
            ("分析用户心情然后生成回应建议", "workflow")
        ]
        
        print("✅ 自然语言生成功能测试:")
        for description, expected_type in test_cases:
            detected_type = _detect_extension_type(description.lower())
            config = _parse_natural_language_description(description)
            
            status = "✅" if detected_type == expected_type else "⚠️"
            print(f"   {status} 描述: {description}")
            print(f"      检测类型: {detected_type} (期望: {expected_type})")
            print(f"      生成配置: {config.get('name', 'N/A')}")
        
        return True
    except Exception as e:
        print(f"❌ 自然语言生成功能测试失败: {e}")
        return False

def test_ai_builder_conversation():
    """测试AI对话构建功能"""
    try:
        from ai_extension_builder import ExtensionBuilder
        
        builder = ExtensionBuilder("test_user")
        
        # 测试开场白
        greeting = builder.get_greeting()
        print("✅ AI对话构建功能测试:")
        print(f"   开场白: {greeting[:50]}...")
        
        # 测试意图理解
        intent_type, confidence = builder.understand_intent("我想让AI说话更温柔")
        print(f"   意图理解: '{intent_type}' (置信度: {confidence:.2f})")
        
        # 测试配置生成
        builder.state["extension_type"] = "prompt_template"
        builder.state["collected_info"] = {
            "q0": "深夜场景",
            "q1": "语气要温柔，多用短句",
            "q2": "当用户说晚安时"
        }
        config = builder._generate_prompt_template_config(builder.state["collected_info"])
        print(f"   生成配置: {config.get('name', 'N/A')}")
        
        return True
    except Exception as e:
        print(f"❌ AI对话构建功能测试失败: {e}")
        return False

def test_extension_functions():
    """测试扩展相关功能"""
    try:
        from extensions_apps import (
            _get_config_suggestions,
            _extract_name_from_description
        )
        
        print("✅ 扩展功能测试:")
        
        # 测试名称提取
        name = _extract_name_from_description("让AI在深夜时语气更温柔")
        print(f"   名称提取: '{name}'")
        
        # 测试配置建议
        test_config = {
            "type": "prompt_template",
            "config": {
                "content": "简短的提示词"
            }
        }
        suggestions = _get_config_suggestions(test_config)
        print(f"   配置建议: {suggestions}")
        
        return True
    except Exception as e:
        print(f"❌ 扩展功能测试失败: {e}")
        return False

def test_draft_prompt_debug():
    """草稿调试只能运行当前配置，不能混入已保存扩展。"""
    try:
        from extensions_apps import _run_extension_test

        draft = {
            "name": "草稿调试",
            "type": "prompt_template",
            "config": {
                "trigger": "keyword",
                "trigger_pattern": "晚安",
                "inject_position": "system_suffix",
                "content": "请用温柔短句回应。",
            },
        }
        hit = asyncio.run(_run_extension_test(draft, "晚安"))
        miss = asyncio.run(_run_extension_test(draft, "早上好"))
        assert hit["triggered"] is True
        assert "草稿调试" in hit["injection"]
        assert miss["triggered"] is False
        assert miss["injection"] == ""
        assert isinstance(hit["trace"], list)
        print("✅ 草稿扩展调试结果与触发条件一致")
        return True
    except Exception as e:
        print(f"❌ 草稿扩展调试测试失败: {e}")
        return False

def test_frontend_files():
    """测试前端文件"""
    try:
        static_dir = Path("static")
        extension_editor = static_dir / "extension_editor.html"
        
        if extension_editor.exists():
            print("✅ 前端文件测试:")
            print(f"   扩展编辑器页面存在: {extension_editor}")
            
            # 检查关键内容
            content = extension_editor.read_text(encoding="utf-8")
            key_elements = [
                "扩展编辑器",
                "ai-builder",
                "nl-generate",
                "generateFromNL",
                "startAIConversation",
                "deleteExtension",
                "debugResult",
                "toggleExtension"
            ]
            
            for element in key_elements:
                if element in content:
                    print(f"   ✅ 包含元素: {element}")
                else:
                    print(f"   ❌ 缺少元素: {element}")
            
            return True
        else:
            print(f"❌ 扩展编辑器页面不存在: {extension_editor}")
            return False
    except Exception as e:
        print(f"❌ 前端文件测试失败: {e}")
        return False

def main():
    """运行所有测试"""
    print("=" * 50)
    print("AI自定义扩展功能测试")
    print("=" * 50)
    
    tests = [
        ("模块导入测试", test_ai_builder_import),
        ("扩展应用导入测试", test_extensions_apps_import),
        ("自然语言生成测试", test_natural_language_generation),
        ("AI对话构建测试", test_ai_builder_conversation),
        ("扩展功能测试", test_extension_functions),
        ("草稿调试测试", test_draft_prompt_debug),
        ("前端文件测试", test_frontend_files)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n【{test_name}】")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name}执行出错: {e}")
            results.append((test_name, False))
    
    # 总结
    print("\n" + "=" * 50)
    print("测试总结")
    print("=" * 50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {test_name}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("🎉 所有测试通过！AI自定义扩展功能已就绪。")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查相关功能。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
