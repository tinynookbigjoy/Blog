#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hugo博客备份工具 - 最终版本

功能：
- 从Hugo博客提取Markdown内容和图片资源
- 智能增量备份
- 路径修正和格式化
- 生成结构化README
"""

import os
import shutil
import re
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any
from dataclasses import dataclass

@dataclass
class ArticleInfo:
    """文章信息数据类"""
    title: str
    filename: str
    path: str
    year: int
    month: int
    day: int
    date_str: str

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")
    
    def get(self, key_path: str, default=None):
        """获取配置项，支持点号分隔的路径"""
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value

class HugoBlogBackup:
    """Hugo博客备份主类"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config = ConfigManager(config_path)
        self._init_paths()
        self._init_filters()
        
        # 存储文章信息和使用的图片
        self.articles = {}
        self.used_images = set()
        
        # 存储变更信息
        self.updated_files = []
        
        # 初始化文章分类
        categories = self.config.get('readme.categories', {})
        for category in categories.keys():
            self.articles[category] = []
    
    def _init_paths(self):
        """初始化路径配置"""
        self.source_root = Path(self.config.get('paths.source_root')).expanduser().resolve()
        self.backup_root = Path(self.config.get('paths.backup_root')).expanduser().resolve()
        
        # 构建完整路径映射
        self.source_dirs = {}
        self.target_dirs = {}
        
        source_dirs_config = self.config.get('paths.source_dirs', {})
        target_dirs_config = self.config.get('paths.target_dirs', {})
        
        for key in source_dirs_config:
            self.source_dirs[key] = self.source_root / source_dirs_config[key]
            self.target_dirs[key] = self.backup_root / target_dirs_config[key]
    
    def _init_filters(self):
        """初始化过滤器配置"""
        self.ignore_files = set(self.config.get('filters.ignore_files', []))
        self.markdown_extensions = set(self.config.get('filters.markdown_extensions', ['.md']))
    
    def log(self, message: str):
        """日志输出"""
        if self.config.get('logging.verbose', True):
            print(message)
    
    def should_ignore_file(self, filename: str) -> bool:
        """检查文件是否应该被忽略"""
        return filename in self.ignore_files
    
    def is_markdown_file(self, filename: str) -> bool:
        """检查是否为markdown文件"""
        return any(filename.lower().endswith(ext) for ext in self.markdown_extensions)
    
    def get_file_hash(self, file_path: Path) -> str:
        """计算文件的MD5哈希值"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return ""
    
    def file_needs_update(self, source_file: Path, target_file: Path) -> bool:
        """检查文件是否需要更新"""
        if not target_file.exists():
            return True
        
        source_hash = self.get_file_hash(source_file)
        target_hash = self.get_file_hash(target_file)
        
        return source_hash != target_hash
    
    def extract_frontmatter_title(self, content: str) -> str:
        """从frontmatter中提取标题"""
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.search(frontmatter_pattern, content, re.DOTALL)
        
        if match:
            frontmatter = match.group(1)
            title_match = re.search(r'title:\s*["\']?(.*?)["\']?\s*$', frontmatter, re.MULTILINE)
            if title_match:
                return title_match.group(1).strip()
        
        return "未知标题"
    
    def extract_image_paths(self, content: str) -> Set[str]:
        """从markdown内容中提取图片路径"""
        image_paths = set()
        img_pattern = r'!\[.*?\]\(([^)]+)\)'
        matches = re.findall(img_pattern, content)
        
        path_patterns = self.config.get('images.path_patterns', [])
        
        for match in matches:
            # 移除可能的锚点标记
            clean_path = match.split('#')[0]
            
            for pattern in path_patterns:
                if clean_path.startswith(pattern):
                    relative_path = clean_path[len(pattern):]
                    image_paths.add(relative_path)
                    break
        
        return image_paths
    
    def fix_paths_in_content(self, content: str) -> str:
        """修正内容中的路径"""
        # 修正图片路径
        img_corrections = self.config.get('path_corrections.images', {})
        from_patterns = img_corrections.get('from_patterns', [])
        to_pattern = img_corrections.get('to_pattern', '')
        
        for pattern in from_patterns:
            escaped_pattern = re.escape(pattern)
            content = re.sub(
                rf'!\[([^\]]*)\]\({escaped_pattern}([^)]+)\)',
                rf'![\1]({to_pattern}\2)',
                content
            )
        
        # 修正文章引用路径
        article_corrections = self.config.get('path_corrections.articles', {})
        for old_dir, new_dir in article_corrections.items():
            old_pattern = f'/{old_dir}/'
            escaped_old = re.escape(old_pattern)
            content = re.sub(
                rf'\[([^\]]+)\]\({escaped_old}([^)]*)?(\))',
                rf'[\1]({new_dir}\2\3)',
                content
            )
            
            # 处理只有目录的引用
            old_pattern_simple = f'/{old_dir}'
            escaped_old_simple = re.escape(old_pattern_simple)
            content = re.sub(
                rf'\[([^\]]+)\]\({escaped_old_simple}(/[^)]*)?(\))',
                rf'[\1]({new_dir.rstrip("/")}\2\3)',
                content
            )
        
        return content
    
    def process_markdown_content(self, content: str) -> Tuple[str, str, Set[str]]:
        """处理markdown内容"""
        title = self.extract_frontmatter_title(content)
        image_paths = self.extract_image_paths(content)
        
        # 移除frontmatter
        frontmatter_pattern = r'^---\s*\n.*?\n---\s*\n'
        content_without_frontmatter = re.sub(frontmatter_pattern, '', content, flags=re.DOTALL)
        
        # 修正路径
        content_with_fixed_paths = self.fix_paths_in_content(content_without_frontmatter)
        
        # 添加标题
        processed_content = f"# {title}\n\n{content_with_fixed_paths.strip()}"
        
        return processed_content, title, image_paths
    
    def extract_date_from_filename(self, filename: str) -> Tuple[int, int, int, str]:
        """从文件名中提取日期信息"""
        date_match = re.match(r'^(\d{4})(\d{2})(\d{2})_', filename)
        if date_match:
            year, month, day = date_match.groups()
            date_format = self.config.get('readme.date_format', 'YYYY-MM-DD')
            if date_format == 'YYYY-MM-DD':
                date_str = f"{year}-{month}-{day}"
            else:
                date_str = f"{year}年{int(month)}月{int(day)}日"
            return (int(year), int(month), int(day), date_str)
        return (0, 0, 0, "")
    
    def ensure_target_dirs(self):
        """确保目标目录存在"""
        for dir_path in self.target_dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def process_markdown_files(self, category: str):
        """处理指定类别的markdown文件"""
        source_dir = self.source_dirs.get(category)
        target_dir = self.target_dirs.get(category)
        
        if not source_dir or not source_dir.exists():
            self.log(f"⚠️  源目录不存在: {source_dir}")
            return
        
        self.log(f"📝 处理 {category} 文件...")
        
        processed_count = 0
        skipped_count = 0
        ignored_count = 0
        
        for file_path in source_dir.rglob('*'):
            if not file_path.is_file() or not self.is_markdown_file(file_path.name):
                continue
            
            if self.should_ignore_file(file_path.name):
                self.log(f"  ⏭️  忽略文件: {file_path.name}")
                ignored_count += 1
                continue
            
            # 计算目标文件路径
            rel_path = file_path.relative_to(source_dir)
            target_file = target_dir / rel_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 读取文件内容用于处理和信息提取
            try:
                content = file_path.read_text(encoding='utf-8')
                title = self.extract_frontmatter_title(content)
                image_paths = self.extract_image_paths(content)
                self.used_images.update(image_paths)
                
                year, month, day, date_str = self.extract_date_from_filename(file_path.name)
                
                article_info = ArticleInfo(
                    title=title,
                    filename=file_path.name,
                    path=str(target_file.relative_to(self.backup_root)),
                    year=year,
                    month=month,
                    day=day,
                    date_str=date_str
                )
                self.articles[category].append(article_info)
                
                # 处理内容
                processed_content, _, _ = self.process_markdown_content(content)
                
                # 检查是否需要更新（比较处理后的内容）
                needs_update = True
                if target_file.exists():
                    try:
                        existing_content = target_file.read_text(encoding='utf-8')
                        needs_update = existing_content != processed_content
                    except Exception:
                        needs_update = True
                
                if not needs_update:
                    self.log(f"  ↔️  跳过文件: {file_path.name} (无变化)")
                    skipped_count += 1
                else:
                    # 写入文件
                    target_file.write_text(processed_content, encoding='utf-8')
                    self.log(f"  ✅ 更新文件: {file_path.name} -> {title}")
                    self.updated_files.append(f"{category}/{file_path.name}")
                    processed_count += 1
                
            except Exception as e:
                self.log(f"  ❌ 处理文件失败 {file_path.name}: {e}")
        
        self.log(f"  📊 {category}: 更新 {processed_count} 个文件，跳过 {skipped_count} 个文件，忽略 {ignored_count} 个文件")
    
    def copy_used_images(self):
        """复制被使用的图片"""
        source_pics = self.source_dirs.get('pics')
        target_pics = self.target_dirs.get('pics')
        
        if not source_pics or not source_pics.exists():
            self.log(f"⚠️  图片目录不存在: {source_pics}")
            return
        
        target_pics.mkdir(parents=True, exist_ok=True)
        
        copied_count = 0
        skipped_count = 0
        
        # 获取所有图片文件
        all_images = set()
        for file_path in source_pics.rglob('*'):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(source_pics))
                all_images.add(rel_path)
        
        # 只处理被使用的图片
        for image_path in self.used_images:
            source_file = source_pics / image_path
            target_file = target_pics / image_path
            
            if not source_file.exists():
                continue
            
            target_file.parent.mkdir(parents=True, exist_ok=True)
            
            if not self.file_needs_update(source_file, target_file):
                skipped_count += 1
                continue
            
            try:
                shutil.copy2(source_file, target_file)
                self.updated_files.append(f"pics/{image_path}")
                copied_count += 1
            except Exception as e:
                self.log(f"  ❌ 复制图片失败 {image_path}: {e}")
        
        unused_count = len(all_images) - len(self.used_images)
        self.log(f"🖼️  图片同步完成: 复制 {copied_count} 个，跳过 {skipped_count} 个，忽略未使用 {unused_count} 个")
        self.log(f"   -> {target_pics}")
    
    def generate_readme(self):
        """生成README文件"""
        readme_title = self.config.get('readme.title', '博客文章备份')
        categories_config = self.config.get('readme.categories', {})
        
        readme_content = f"# {readme_title}\n\n"
        
        # 按配置的顺序处理分类
        sorted_categories = sorted(categories_config.items(), key=lambda x: x[1].get('order', 999))
        
        for category_key, category_config in sorted_categories:
            category_name = category_config.get('name', category_key)
            readme_content += f"# {category_name}\n\n"
            
            articles = self.articles.get(category_key, [])
            if articles:
                # 按年份分组
                articles_by_year = {}
                for article in articles:
                    if article.year > 0:
                        if article.year not in articles_by_year:
                            articles_by_year[article.year] = []
                        articles_by_year[article.year].append(article)
                
                # 按年份倒序
                for year in sorted(articles_by_year.keys(), reverse=True):
                    readme_content += f"## {year}\n\n"
                    
                    # 按日期倒序
                    year_articles = sorted(
                        articles_by_year[year],
                        key=lambda x: (x.year, x.month, x.day),
                        reverse=True
                    )
                    
                    for article in year_articles:
                        if article.date_str:
                            readme_content += f"* {article.date_str} [{article.title}]({article.path})\n"
                        else:
                            readme_content += f"* [{article.title}]({article.path})\n"
                    
                    readme_content += "\n"
                
                # 处理没有日期的文章
                no_date_articles = [a for a in articles if a.year == 0]
                if no_date_articles:
                    readme_content += "## 其他\n\n"
                    for article in no_date_articles:
                        readme_content += f"* [{article.title}]({article.path})\n"
                    readme_content += "\n"
            else:
                readme_content += "暂无内容\n\n"
        
        # 写入README文件
        readme_path = self.backup_root / "README.md"
        readme_path.write_text(readme_content, encoding='utf-8')
        
        self.log(f"✅ README.md 已生成: {readme_path}")
    
    def show_statistics(self):
        """显示统计信息"""
        if not self.config.get('logging.show_stats', True):
            return
        
        total_articles = sum(len(articles) for articles in self.articles.values())
        
        self.log("📊 统计信息:")
        for category, articles in self.articles.items():
            category_config = self.config.get(f'readme.categories.{category}', {})
            category_name = category_config.get('name', category)
            self.log(f"  - {category_name}: {len(articles)} 篇")
        
        self.log(f"  - 总计: {total_articles} 篇")
        self.log(f"  - 使用的图片: {len(self.used_images)} 个")
        
        # 显示变更汇总
        if self.updated_files:
            self.log(f"🔄 本次更新了 {len(self.updated_files)} 个文件:")
            for file_path in self.updated_files:
                self.log(f"  - {file_path}")
        else:
            self.log("✨ 本次运行无更新")
    
    def backup(self):
        """执行完整的备份流程"""
        self.log("🚀 开始Hugo博客备份...")
        self.log(f"源路径: {self.source_root}")
        self.log(f"备份路径: {self.backup_root}")
        self.log("-" * 50)
        
        # 1. 创建目录结构
        self.ensure_target_dirs()
        self.log("✅ 目录结构创建完成")
        
        # 2. 处理各类别的markdown文件
        for category in self.source_dirs.keys():
            if category != 'pics':
                self.process_markdown_files(category)
        
        # 3. 复制被使用的图片
        self.copy_used_images()
        
        # 4. 生成README
        self.generate_readme()
        
        self.log("-" * 50)
        self.log("🎉 备份完成!")
        self.log(f"备份文件位置: {self.backup_root}")
        
        # 5. 显示统计信息
        self.show_statistics()

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Hugo博客备份工具')
    parser.add_argument('--config', '-c', default='config.json', help='配置文件路径')
    args = parser.parse_args()
    
    try:
        backup_tool = HugoBlogBackup(args.config)
        backup_tool.backup()
    except Exception as e:
        print(f"❌ 备份失败: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())