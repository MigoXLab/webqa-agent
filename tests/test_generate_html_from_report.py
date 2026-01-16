#!/usr/bin/env python3
"""脚本：从report路径生成HTML报告.

用法:     python generate_html_from_report.py <report_path> [--language zh-CN|en-
US] [--mode gen|run]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from webqa_agent.executor.result_aggregator import ResultAggregator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class DummyTestSession:
    """一个简单的测试会话对象，用于生成HTML报告."""
    def __init__(self, report_path: str):
        self.report_path = report_path

    def to_dict(self):
        """返回一个空字典作为fallback."""
        return {}


def detect_mode(report_dir: str) -> str:
    """自动检测报告模式（gen或run）"""
    test_results_path = Path(report_dir) / 'test_results.json'
    if test_results_path.exists():
        try:
            with open(test_results_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 检查是否有gen或run键
                if 'gen' in data:
                    return 'gen'
                elif 'run' in data:
                    return 'run'
        except Exception as e:
            logging.warning(f'无法读取test_results.json来检测模式: {e}')

    # 检查目录中是否有case相关的文件
    report_path = Path(report_dir)
    if (report_path / 'cases.json').exists():
        return 'run'

    # 默认返回gen
    return 'gen'


def generate_html_from_report(
    report_path: str,
    language: str = 'zh-CN',
    mode: str = None
) -> str:
    """从report路径生成HTML报告.

    Args:
        report_path: 报告目录路径
        language: 报告语言 (zh-CN 或 en-US)
        mode: 报告模式 (gen 或 run)，如果为None则自动检测

    Returns:
        生成的HTML文件路径
    """
    report_dir = Path(report_path).resolve()

    if not report_dir.exists():
        raise FileNotFoundError(f'报告目录不存在: {report_dir}')

    if not report_dir.is_dir():
        raise ValueError(f'路径不是目录: {report_dir}')

    # 自动检测模式
    if mode is None:
        mode = detect_mode(str(report_dir))
        logging.info(f'自动检测到模式: {mode}')

    # 创建ResultAggregator
    report_config = {
        'language': language,
        'report_dir': str(report_dir)
    }
    aggregator = ResultAggregator(report_config=report_config)

    # 检查test_results.json是否存在
    test_results_path = report_dir / 'test_results.json'
    aggregated_data = None

    if test_results_path.exists():
        logging.info(f'找到test_results.json: {test_results_path}')
        try:
            with open(test_results_path, 'r', encoding='utf-8') as f:
                aggregated_data = json.load(f)
        except Exception as e:
            logging.warning(f'读取test_results.json失败: {e}，将尝试聚合数据')
    else:
        logging.info('未找到test_results.json，尝试聚合数据...')

    # 如果test_results.json不存在或读取失败，尝试聚合
    if aggregated_data is None:
        try:
            aggregated_data, _ = aggregator.aggregate_report_json(mode, str(report_dir))
            logging.info('数据聚合完成')
        except Exception as e:
            logging.warning(f'数据聚合失败: {e}')
            aggregated_data = None

    # 创建dummy test session
    dummy_session = DummyTestSession(str(report_dir))

    # 生成HTML报告
    logging.info('正在生成HTML报告...')
    html_path = aggregator.generate_html_report_fully_inlined(
        test_session=dummy_session,
        report_dir=str(report_dir),
        aggregated_data=aggregated_data
    )

    if html_path:
        logging.info(f'✅ HTML报告生成成功: {html_path}')
        return html_path
    else:
        raise RuntimeError('HTML报告生成失败')


def main():
    parser = argparse.ArgumentParser(
        description='从report路径生成HTML报告',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        'report_path',
        type=str,
        help='报告目录路径'
    )

    parser.add_argument(
        '--language',
        type=str,
        choices=['zh-CN', 'en-US'],
        default='zh-CN',
        help='报告语言 (默认: zh-CN)'
    )

    parser.add_argument(
        '--mode',
        type=str,
        choices=['gen', 'run'],
        default=None,
        help='报告模式 (gen或run)，如果不指定则自动检测'
    )

    args = parser.parse_args()

    try:
        html_path = generate_html_from_report(
            report_path=args.report_path,
            language=args.language,
            mode=args.mode
        )
        print(f'\n📄 HTML报告已生成: {html_path}')
        sys.exit(0)
    except Exception as e:
        logging.error(f'❌ 生成HTML报告失败: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
