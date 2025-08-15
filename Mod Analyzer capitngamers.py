import os
import json
import zipfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import webbrowser
from pathlib import Path
import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import time
from concurrent.futures import ThreadPoolExecutor
import sqlite3

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.parse
    HAS_REQUESTS = False

@dataclass
class ModInfo:
    name: str
    version: str
    mc_version: str
    mod_loader: str
    file_path: str
    size: int
    dependencies: List[str]
    conflicts: List[str]
    memory_usage: int
    performance_impact: str
    mod_id: str

class ModAnalyzer:
    def __init__(self):
        self.mods = []
        self.compatibility_db = {}
        self.performance_db = {}
        self.init_database()
        
    def init_database(self):
        try:
            self.conn = sqlite3.connect('mod_compatibility.db')
            cursor = self.conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mod_compatibility (
                    mod1 TEXT,
                    mod2 TEXT,
                    compatibility_score REAL,
                    issues TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mod_performance (
                    mod_name TEXT PRIMARY KEY,
                    memory_usage INTEGER,
                    cpu_impact TEXT,
                    performance_score REAL,
                    min_ram INTEGER,
                    recommended_ram INTEGER
                )
            ''')
            
            self.conn.commit()
        except Exception as e:
            print(f"خطا در ایجاد پایگاه داده: {e}")
            self.conn = None

    def analyze_mod_file(self, file_path: str) -> Optional[ModInfo]:
        try:
            if file_path.endswith('.jar'):
                return self._analyze_jar_mod(file_path)
            elif file_path.endswith('.zip'):
                return self._analyze_zip_mod(file_path)
            return None
        except Exception as e:
            print(f"خطا در تحلیل {file_path}: {e}")
            return None

    def _extract_mod_id(self, data: dict, mod_loader: str, file_path) -> str:
        mod_id = "unknown"
        
        try:
            if mod_loader == 'Forge':
                mod_id = data.get('modid', '')
                if not mod_id and isinstance(data, list) and data:
                    mod_id = data[0].get('modid', '')
                
                if not mod_id:
                    mod_id = data.get('name', '').lower().replace(' ', '_')
                    
            elif mod_loader == 'Fabric':
                mod_id = data.get('id', '')
                if not mod_id:
                    mod_id = data.get('name', '').lower().replace(' ', '_')
                    
            if not mod_id or mod_id == "unknown":
                filename = os.path.basename(file_path)
                mod_id = filename.split('-')[0].lower()
                
        except Exception as e:
            print(f"خطا در استخراج Mod ID: {e}")
            
        return mod_id if mod_id else "unknown"

    def _analyze_jar_mod(self, file_path: str) -> Optional[ModInfo]:
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                if 'mcmod.info' in zip_file.namelist():
                    return self._parse_forge_mod(zip_file, file_path)
                
                elif 'fabric.mod.json' in zip_file.namelist():
                    return self._parse_fabric_mod(zip_file, file_path)
                
                elif 'META-INF/mods.toml' in zip_file.namelist():
                    return self._parse_forge_toml_mod(zip_file, file_path)
                
                else:
                    return self._parse_generic_mod(file_path)
                    
        except Exception as e:
            print(f"خطا در تحلیل JAR: {e}")
        return None

    def _analyze_zip_mod(self, file_path: str) -> Optional[ModInfo]:
        return self._parse_generic_mod(file_path)

    def _parse_forge_mod(self, zip_file, file_path: str) -> ModInfo:
        try:
            with zip_file.open('mcmod.info') as f:
                content = f.read().decode('utf-8')
                data = json.loads(content)
                if isinstance(data, list):
                    data = data[0] if data else {}
                
                mod_id = self._extract_mod_id(data, 'Forge', file_path)
                
                return ModInfo(
                    name=data.get('name', 'Unknown'),
                    version=data.get('version', 'Unknown'),
                    mc_version=data.get('mcversion', 'Unknown'),
                    mod_loader='Forge',
                    file_path=file_path,
                    size=os.path.getsize(file_path),
                    dependencies=data.get('dependencies', []),
                    conflicts=[],
                    memory_usage=self._estimate_memory_usage(file_path),
                    performance_impact=self._estimate_performance_impact(data.get('name', '')),
                    mod_id=mod_id
                )
        except Exception as e:
            print(f"خطا در پارس Forge mod: {e}")
            return self._parse_generic_mod(file_path)

    def _parse_fabric_mod(self, zip_file, file_path: str) -> ModInfo:
        try:
            with zip_file.open('fabric.mod.json') as f:
                content = f.read().decode('utf-8')
                data = json.loads(content)
                
                mod_id = self._extract_mod_id(data, 'Fabric', file_path)
                
                depends = data.get('depends', {})
                mc_version = depends.get('minecraft', 'Unknown')
                if isinstance(mc_version, dict):
                    mc_version = str(mc_version)
                
                return ModInfo(
                    name=data.get('name', 'Unknown'),
                    version=data.get('version', 'Unknown'),
                    mc_version=str(mc_version),
                    mod_loader='Fabric',
                    file_path=file_path,
                    size=os.path.getsize(file_path),
                    dependencies=list(depends.keys()),
                    conflicts=[],
                    memory_usage=self._estimate_memory_usage(file_path),
                    performance_impact=self._estimate_performance_impact(data.get('name', '')),
                    mod_id=mod_id
                )
        except Exception as e:
            print(f"خطا در پارس Fabric mod: {e}")
            return self._parse_generic_mod(file_path)

    def _parse_forge_toml_mod(self, zip_file, file_path: str) -> ModInfo:
        try:
            with zip_file.open('META-INF/mods.toml') as f:
                content = f.read().decode('utf-8')
                
                name_match = re.search(r'displayName\s*=\s*"([^"]*)"', content)
                version_match = re.search(r'version\s*=\s*"([^"]*)"', content)
                mc_version_match = re.search(r'minecraftVersion\s*=\s*"([^"]*)"', content)
                mod_id_match = re.search(r'modId\s*=\s*"([^"]*)"', content)
                
                mod_id = mod_id_match.group(1) if mod_id_match else 'unknown'
                
                return ModInfo(
                    name=name_match.group(1) if name_match else 'Unknown',
                    version=version_match.group(1) if version_match else 'Unknown',
                    mc_version=mc_version_match.group(1) if mc_version_match else 'Unknown',
                    mod_loader='Forge',
                    file_path=file_path,
                    size=os.path.getsize(file_path),
                    dependencies=[],
                    conflicts=[],
                    memory_usage=self._estimate_memory_usage(file_path),
                    performance_impact='medium',
                    mod_id=mod_id
                )
        except Exception as e:
            print(f"خطا در پارس Forge TOML mod: {e}")
            return self._parse_generic_mod(file_path)

    def _parse_generic_mod(self, file_path: str) -> ModInfo:
        filename = os.path.basename(file_path)
        name = filename.rsplit('.', 1)[0]
        
        mod_id = name.split('-')[0].lower().replace(' ', '_')
        
        return ModInfo(
            name=name,
            version='Unknown',
            mc_version='Unknown',
            mod_loader='Unknown',
            file_path=file_path,
            size=os.path.getsize(file_path),
            dependencies=[],
            conflicts=[],
            memory_usage=self._estimate_memory_usage(file_path),
            performance_impact=self._estimate_performance_impact(name),
            mod_id=mod_id
        )

    def _estimate_memory_usage(self, file_path: str) -> int:
        try:
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            
            if size_mb < 1:
                return 32
            elif size_mb < 5:
                return 64
            elif size_mb < 20:
                return 128
            else:
                return 256
        except:
            return 64

    def _estimate_performance_impact(self, mod_name: str) -> str:
        high_impact_mods = ['optifine', 'shaders', 'twilight forest', 'thaumcraft', 'industrial craft', 'thermal', 'mekanism']
        medium_impact_mods = ['buildcraft', 'thermal expansion', 'tinkers construct', 'applied energistics', 'forestry']
        
        mod_name_lower = mod_name.lower()
        
        for mod in high_impact_mods:
            if mod in mod_name_lower:
                return 'high'
        
        for mod in medium_impact_mods:
            if mod in mod_name_lower:
                return 'medium'
        
        return 'low'

    def scan_directory(self, directory: str, progress_callback=None) -> List[ModInfo]:
        self.mods = []
        mod_files = []
        
        try:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith(('.jar', '.zip')):
                        mod_files.append(os.path.join(root, file))
        except Exception as e:
            print(f"خطا در اسکن دایرکتوری: {e}")
            return []
        
        total_files = len(mod_files)
        
        for i, file_path in enumerate(mod_files):
            if progress_callback:
                progress_callback(i + 1, total_files)
            
            mod_info = self.analyze_mod_file(file_path)
            if mod_info:
                self.mods.append(mod_info)
        
        return self.mods

    def export_mod_list_txt(self, output_path: str) -> bool:
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("لیست فایل‌های ماد\n")
                f.write("=" * 50 + "\n\n")
                
                for mod in self.mods:
                    filename = os.path.basename(mod.file_path)
                    f.write(f"{filename}\n")
                    
            return True
        except Exception as e:
            print(f"خطا در ذخیره لیست فایل‌ها: {e}")
            return False

    def export_mod_whitelist(self, output_path: str) -> bool:
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("# Minecraft Server Mod Whitelist\n")
                f.write("# Generated by Mod Analyzer\n")
                f.write(f"# Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("# Total mods: {}\n\n".format(len(self.mods)))
                
                for mod in self.mods:
                    f.write(f"{mod.mod_id}\n")
                    
            return True
        except Exception as e:
            print(f"خطا در ذخیره whitelist: {e}")
            return False

    def check_compatibility(self) -> Dict[str, float]:
        compatibility_scores = {}
        
        if not self.mods:
            return {'overall': 0.0}
        
        mc_versions = set(mod.mc_version for mod in self.mods if mod.mc_version != 'Unknown')
        if len(mc_versions) > 1:
            compatibility_scores['minecraft_version'] = 0.3
        else:
            compatibility_scores['minecraft_version'] = 1.0
        
        loaders = set(mod.mod_loader for mod in self.mods if mod.mod_loader != 'Unknown')
        if len(loaders) > 1:
            compatibility_scores['mod_loader'] = 0.2
        else:
            compatibility_scores['mod_loader'] = 1.0
        
        all_mod_names = set(mod.name.lower() for mod in self.mods)
        missing_deps = []
        
        for mod in self.mods:
            for dep in mod.dependencies:
                if dep.lower() not in all_mod_names and dep not in ['minecraft', 'forge', 'fabric']:
                    missing_deps.append(f"{mod.name} needs {dep}")
        
        if missing_deps:
            compatibility_scores['dependencies'] = max(0.0, 1.0 - len(missing_deps) * 0.1)
        else:
            compatibility_scores['dependencies'] = 1.0
        
        if compatibility_scores:
            overall_score = sum(compatibility_scores.values()) / len(compatibility_scores)
        else:
            overall_score = 0.0
        compatibility_scores['overall'] = overall_score
        
        return compatibility_scores

    def calculate_hardware_requirements(self) -> Dict[str, any]:
        if not self.mods:
            return {
                'total_ram_mb': 2048,
                'total_ram_gb': 2.0,
                'cpu_recommendation': 'Intel i3 یا AMD Ryzen 3',
                'gpu_recommendation': 'GTX 1050 یا معادل',
                'high_impact_mods': 0,
                'total_mods': 0
            }
        
        total_memory = sum(mod.memory_usage for mod in self.mods)
        high_impact_count = sum(1 for mod in self.mods if mod.performance_impact == 'high')
        medium_impact_count = sum(1 for mod in self.mods if mod.performance_impact == 'medium')
        
        base_ram = 2048
        mod_ram = total_memory
        extra_ram = high_impact_count * 512 + medium_impact_count * 256
        
        total_ram = base_ram + mod_ram + extra_ram
        
        if high_impact_count > 5:
            cpu_recommendation = "Intel i7/i9 یا AMD Ryzen 7/9 (حداقل 8 هسته)"
        elif high_impact_count > 2:
            cpu_recommendation = "Intel i5 یا AMD Ryzen 5 (حداقل 6 هسته)"
        else:
            cpu_recommendation = "Intel i3 یا AMD Ryzen 3 (حداقل 4 هسته)"
        
        shader_mods = any('shader' in mod.name.lower() or 'optifine' in mod.name.lower() for mod in self.mods)
        if shader_mods:
            gpu_recommendation = "GTX 1660/RTX 2060 یا بالاتر"
        else:
            gpu_recommendation = "GTX 1050 یا معادل"
        
        return {
            'total_ram_mb': total_ram,
            'total_ram_gb': round(total_ram / 1024, 1),
            'cpu_recommendation': cpu_recommendation,
            'gpu_recommendation': gpu_recommendation,
            'high_impact_mods': high_impact_count,
            'total_mods': len(self.mods)
        }

    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

class ModAnalyzerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎮 ماینکرفت ماد آنالایزر")
        self.root.geometry("1200x800")
        
        self.bg_color = '#1c2733'
        self.secondary_bg = '#242f3d'
        self.accent_color = '#3390ec'
        self.text_color = '#ffffff'
        self.secondary_text = '#8b9aab'
        
        self.root.configure(bg=self.bg_color)
        
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'), 
                       background=self.bg_color, foreground=self.text_color)
        style.configure('Header.TLabel', font=('Arial', 12, 'bold'), 
                       background=self.bg_color, foreground=self.accent_color)
        style.configure('Custom.TButton', font=('Arial', 10, 'bold'),
                       background=self.accent_color, foreground=self.text_color)
        style.map('Custom.TButton',
                 background=[('active', '#2b7bc7')])
        
        style.configure("Treeview", 
                       background=self.secondary_bg,
                       foreground=self.text_color,
                       fieldbackground=self.secondary_bg,
                       borderwidth=0)
        style.configure("Treeview.Heading",
                       background=self.bg_color,
                       foreground=self.accent_color,
                       borderwidth=0)
        style.map('Treeview', background=[('selected', self.accent_color)])
        
        style.configure('TNotebook', background=self.bg_color, borderwidth=0)
        style.configure('TNotebook.Tab', background=self.secondary_bg, 
                       foreground=self.secondary_text, padding=[20, 10])
        style.map('TNotebook.Tab', 
                 background=[('selected', self.bg_color)],
                 foreground=[('selected', self.text_color)])
        
        self.analyzer = ModAnalyzer()
        self.setup_ui()
        
    def setup_ui(self):
        title_frame = tk.Frame(self.root, bg=self.bg_color)
        title_frame.pack(fill='x', padx=10, pady=5)
        
        title_label = ttk.Label(title_frame, text=" ماینکرفت ماد آنالایزر CapitanGamers ", style='Title.TLabel')
        title_label.pack()
        
        path_frame = tk.Frame(self.root, bg=self.bg_color)
        path_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(path_frame, text="📁 مسیر پوشه ماد ها:", style='Header.TLabel').pack(anchor='w')
        
        path_input_frame = tk.Frame(path_frame, bg=self.bg_color)
        path_input_frame.pack(fill='x', pady=5)
        
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(path_input_frame, textvariable=self.path_var, 
                                  font=('Arial', 10), width=80,
                                  bg=self.secondary_bg, fg=self.text_color,
                                  insertbackground=self.text_color)
        self.path_entry.pack(side='left', fill='x', expand=True)
        
        browse_btn = ttk.Button(path_input_frame, text="انتخاب پوشه", command=self.browse_folder, style='Custom.TButton')
        browse_btn.pack(side='right', padx=(5, 0))
        
        analyze_btn = ttk.Button(path_input_frame, text="🔍 تحلیل ماد ها", command=self.analyze_mods, style='Custom.TButton')
        analyze_btn.pack(side='right', padx=(5, 0))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(path_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill='x', pady=5)
        
        self.progress_label = ttk.Label(path_frame, text="آماده برای تحلیل...", 
                                       background=self.bg_color, foreground=self.secondary_text)
        self.progress_label.pack()
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.setup_mods_tab()
        self.setup_compatibility_tab()
        self.setup_hardware_tab()
        self.setup_report_tab()

    def setup_mods_tab(self):
        mods_frame = ttk.Frame(self.notebook)
        self.notebook.add(mods_frame, text="📦 لیست ماد ها")
        
        export_frame = tk.Frame(mods_frame, bg=self.secondary_bg)
        export_frame.pack(fill='x', padx=5, pady=5)
        
        export_list_btn = ttk.Button(export_frame, text="📄 خروجی لیست فایل‌ها", 
                                    command=self.export_file_list, style='Custom.TButton')
        export_list_btn.pack(side='left', padx=5)
        
        export_whitelist_btn = ttk.Button(export_frame, text="📋 خروجی Whitelist", 
                                         command=self.export_whitelist, style='Custom.TButton')
        export_whitelist_btn.pack(side='left', padx=5)
        
        columns = ('نام', 'ورژن', 'ورژن MC', 'لودر', 'سایز', 'تأثیر عملکرد', 'Mod ID')
        self.mods_tree = ttk.Treeview(mods_frame, columns=columns, show='headings', height=15)
        
        column_widths = {
            'نام': 200,
            'ورژن': 100,
            'ورژن MC': 80,
            'لودر': 80,
            'سایز': 80,
            'تأثیر عملکرد': 100,
            'Mod ID': 150
        }
        
        for col in columns:
            self.mods_tree.heading(col, text=col)
            self.mods_tree.column(col, width=column_widths.get(col, 100))
        
        scrollbar = ttk.Scrollbar(mods_frame, orient='vertical', command=self.mods_tree.yview)
        self.mods_tree.configure(yscrollcommand=scrollbar.set)
        
        self.mods_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

    def setup_compatibility_tab(self):
        compatibility_frame = ttk.Frame(self.notebook)
        self.notebook.add(compatibility_frame, text="🔗 سازگاری")
        
        results_frame = tk.Frame(compatibility_frame, bg=self.secondary_bg)
        results_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        ttk.Label(results_frame, text="📊 نتایج سازگاری ماد ها", style='Header.TLabel').pack(anchor='w')
        
        self.compatibility_text = scrolledtext.ScrolledText(results_frame, height=20, width=80, 
                                                          font=('Arial', 10), 
                                                          bg=self.secondary_bg, 
                                                          fg=self.text_color,
                                                          insertbackground=self.text_color)
        self.compatibility_text.pack(fill='both', expand=True, pady=5)

    def setup_hardware_tab(self):
        hardware_frame = ttk.Frame(self.notebook)
        self.notebook.add(hardware_frame, text="💻 نیازمندی سخت افزار")
        
        hw_results_frame = tk.Frame(hardware_frame, bg=self.secondary_bg)
        hw_results_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        ttk.Label(hw_results_frame, text="⚙️ پیشنهادات سخت افزاری", style='Header.TLabel').pack(anchor='w')
        
        self.hardware_text = scrolledtext.ScrolledText(hw_results_frame, height=20, width=80,
                                                     font=('Arial', 10), 
                                                     bg=self.secondary_bg, 
                                                     fg=self.text_color,
                                                     insertbackground=self.text_color)
        self.hardware_text.pack(fill='both', expand=True, pady=5)

    def setup_report_tab(self):
        report_frame = ttk.Frame(self.notebook)
        self.notebook.add(report_frame, text="📋 گزارش کامل")
        
        report_results_frame = tk.Frame(report_frame, bg=self.secondary_bg)
        report_results_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        button_frame = tk.Frame(report_results_frame, bg=self.secondary_bg)
        button_frame.pack(fill='x', pady=5)
        
        save_btn = ttk.Button(button_frame, text="💾 ذخیره گزارش", command=self.save_report, style='Custom.TButton')
        save_btn.pack(side='left', padx=5)
        
        export_btn = ttk.Button(button_frame, text="📄 خروجی JSON", command=self.export_json, style='Custom.TButton')
        export_btn.pack(side='left', padx=5)
        
        self.report_text = scrolledtext.ScrolledText(report_results_frame, height=18, width=80,
                                                   font=('Arial', 9), 
                                                   bg=self.secondary_bg, 
                                                   fg=self.text_color,
                                                   insertbackground=self.text_color)
        self.report_text.pack(fill='both', expand=True, pady=5)

    def browse_folder(self):
        folder = filedialog.askdirectory(title="انتخاب پوشه ماد ها")
        if folder:
            self.path_var.set(folder)

    def update_progress(self, current, total):
        if total > 0:
            progress = (current / total) * 100
            self.progress_var.set(progress)
            self.progress_label.config(text=f"در حال تحلیل: {current}/{total} ماد")
            self.root.update()

    def analyze_mods(self):
        if not self.path_var.get():
            messagebox.showerror("خطا", "لطفاً مسیر پوشه ماد ها را انتخاب کنید")
            return
        
        if not os.path.exists(self.path_var.get()):
            messagebox.showerror("خطا", "مسیر انتخاب شده وجود ندارد")
            return
        
        thread = threading.Thread(target=self._analyze_thread)
        thread.daemon = True
        thread.start()

    def _analyze_thread(self):
        try:
            self.analyzer.scan_directory(self.path_var.get(), self.update_progress)
            self.root.after(0, self.display_results)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("خطا", f"خطا در تحلیل: {str(e)}"))

    def display_results(self):
        for item in self.mods_tree.get_children():
            self.mods_tree.delete(item)
        
        for mod in self.analyzer.mods:
            try:
                size_mb = round(mod.size / (1024 * 1024), 2)
                self.mods_tree.insert('', 'end', values=(
                    mod.name,
                    mod.version,
                    mod.mc_version,
                    mod.mod_loader,
                    f"{size_mb} MB",
                    mod.performance_impact,
                    mod.mod_id
                ))
            except Exception as e:
                print(f"خطا در نمایش ماد {mod.name}: {e}")
        
        self.display_compatibility_results()
        self.display_hardware_requirements()
        self.display_full_report()
        
        self.progress_label.config(text=f"تحلیل کامل شد - {len(self.analyzer.mods)} ماد پیدا شد")

    def export_file_list(self):
        if not self.analyzer.mods:
            messagebox.showwarning("هشدار", "ابتدا ماد ها را تحلیل کنید")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="ذخیره لیست فایل‌ها",
            initialfile="mods_list.txt"
        )
        
        if file_path:
            if self.analyzer.export_mod_list_txt(file_path):
                messagebox.showinfo("موفقیت", "لیست فایل‌ها با موفقیت ذخیره شد")
            else:
                messagebox.showerror("خطا", "خطا در ذخیره لیست فایل‌ها")

    def export_whitelist(self):
        if not self.analyzer.mods:
            messagebox.showwarning("هشدار", "ابتدا ماد ها را تحلیل کنید")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="ذخیره Whitelist",
            initialfile="mod_whitelist.txt"
        )
        
        if file_path:
            if self.analyzer.export_mod_whitelist(file_path):
                messagebox.showinfo("موفقیت", "Whitelist با موفقیت ذخیره شد")
            else:
                messagebox.showerror("خطا", "خطا در ذخیره Whitelist")

    def display_compatibility_results(self):
        try:
            compatibility = self.analyzer.check_compatibility()
            
            text = "🔍 تحلیل سازگاری ماد ها\n"
            text += "=" * 50 + "\n\n"
            
            overall_score = compatibility.get('overall', 0) * 100
            text += f"📊 امتیاز سازگاری کلی: {overall_score:.1f}%\n\n"
            
            if overall_score >= 80:
                text += "✅ سازگاری عالی - مشکل خاصی پیش بینی نمی شود\n\n"
            elif overall_score >= 60:
                text += "⚠️ سازگاری متوسط - ممکن است مشکلات جزئی داشته باشید\n\n"
            else:
                text += "❌ سازگاری ضعیف - مشکلات جدی احتمال دارد\n\n"
            
            text += "📋 جزئیات سازگاری:\n"
            text += f"• ورژن ماینکرفت: {compatibility.get('minecraft_version', 0) * 100:.1f}%\n"
            text += f"• نوع لودر: {compatibility.get('mod_loader', 0) * 100:.1f}%\n"
            text += f"• وابستگی ها: {compatibility.get('dependencies', 0) * 100:.1f}%\n\n"
            
            mc_versions = set(mod.mc_version for mod in self.analyzer.mods if mod.mc_version != 'Unknown')
            loaders = set(mod.mod_loader for mod in self.analyzer.mods if mod.mod_loader != 'Unknown')
            
            text += "📈 آمار کلی:\n"
            text += f"• تعداد کل ماد ها: {len(self.analyzer.mods)}\n"
            text += f"• ورژن های ماینکرفت: {', '.join(mc_versions) if mc_versions else 'نامشخص'}\n"
            text += f"• انواع لودر: {', '.join(loaders) if loaders else 'نامشخص'}\n"
            
            self.compatibility_text.delete(1.0, tk.END)
            self.compatibility_text.insert(1.0, text)
        except Exception as e:
            self.compatibility_text.delete(1.0, tk.END)
            self.compatibility_text.insert(1.0, f"خطا در نمایش نتایج سازگاری: {e}")

    def display_hardware_requirements(self):
        try:
            hw_req = self.analyzer.calculate_hardware_requirements()
            
            text = "💻 پیشنهادات سخت افزاری\n"
            text += "=" * 50 + "\n\n"
            
            text += f"🎯 تنظیمات پیشنهادی برای {hw_req['total_mods']} ماد:\n\n"
            
            text += f"🧠 حافظه (RAM):\n"
            text += f"• حداقل: {hw_req['total_ram_gb']} گیگابایت\n"
            text += f"• پیشنهادی: {hw_req['total_ram_gb'] + 2} گیگابایت\n"
            text += f"• برای عملکرد بهتر: {hw_req['total_ram_gb'] + 4} گیگابایت\n\n"
            
            text += f"⚡ پردازنده (CPU):\n"
            text += f"• {hw_req['cpu_recommendation']}\n\n"
            
            text += f"🎮 کارت گرافیک (GPU):\n"
            text += f"• {hw_req['gpu_recommendation']}\n\n"
            
            text += f"⚙️ تنظیمات پیشنهادی JVM:\n"
            text += f"• -Xmx{int(hw_req['total_ram_gb'] * 1024)}M\n"
            text += f"• -Xms{int(hw_req['total_ram_gb'] * 512)}M\n"
            text += f"• -XX:+UseG1GC\n"
            text += f"• -XX:G1HeapRegionSize=32M\n\n"
            
            if hw_req['high_impact_mods'] > 3:
                text += "⚠️ هشدار: تعداد زیادی ماد با تأثیر بالا روی عملکرد دارید\n"
                text += "  • عملکرد سرور ممکن است کند شود\n"
                text += "  • مصرف منابع بالا خواهد بود\n\n"
            
            text += "🔧 پیشنهادات بهینه سازی:\n"
            text += "• از OptiFine یا Sodium استفاده کنید\n"
            text += "• تنظیمات گرافیکی را کاهش دهید\n"
            text += "• ماد های غیرضروری را حذف کنید\n"
            text += "• فاصله رندر را کم کنید\n"
            
            self.hardware_text.delete(1.0, tk.END)
            self.hardware_text.insert(1.0, text)
        except Exception as e:
            self.hardware_text.delete(1.0, tk.END)
            self.hardware_text.insert(1.0, f"خطا در نمایش نیازمندی های سخت افزاری: {e}")

    def display_full_report(self):
        try:
            report = "📋 گزارش کامل تحلیل ماد ها\n"
            report += "=" * 60 + "\n\n"
            
            report += f"📅 تاریخ تحلیل: {time.strftime('%Y/%m/%d %H:%M:%S')}\n"
            report += f"📁 مسیر تحلیل شده: {self.path_var.get()}\n"
            report += f"📦 تعداد ماد ها: {len(self.analyzer.mods)}\n\n"
            
            report += "📋 جزئیات ماد ها:\n"
            report += "-" * 40 + "\n"
            
            for i, mod in enumerate(self.analyzer.mods, 1):
                report += f"{i}. {mod.name}\n"
                report += f"   • ورژن: {mod.version}\n"
                report += f"   • ورژن MC: {mod.mc_version}\n"
                report += f"   • لودر: {mod.mod_loader}\n"
                report += f"   • سایز: {round(mod.size / (1024 * 1024), 2)} MB\n"
                report += f"   • تأثیر عملکرد: {mod.performance_impact}\n"
                report += f"   • حافظه تخمینی: {mod.memory_usage} MB\n"
                report += f"   • Mod ID: {mod.mod_id}\n"
                if mod.dependencies:
                    report += f"   • وابستگی ها: {', '.join(mod.dependencies)}\n"
                report += "\n"
            
            compatibility = self.analyzer.check_compatibility()
            report += f"🔗 امتیاز سازگاری: {compatibility.get('overall', 0) * 100:.1f}%\n\n"
            
            hw_req = self.analyzer.calculate_hardware_requirements()
            report += f"💻 حافظه پیشنهادی: {hw_req['total_ram_gb']} GB\n"
            report += f"⚡ CPU: {hw_req['cpu_recommendation']}\n"
            report += f"🎮 GPU: {hw_req['gpu_recommendation']}\n"
            
            self.report_text.delete(1.0, tk.END)
            self.report_text.insert(1.0, report)
        except Exception as e:
            self.report_text.delete(1.0, tk.END)
            self.report_text.insert(1.0, f"خطا در تولید گزارش: {e}")

    def save_report(self):
        if not self.analyzer.mods:
            messagebox.showwarning("هشدار", "ابتدا ماد ها را تحلیل کنید")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="ذخیره گزارش"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.report_text.get(1.0, tk.END))
                messagebox.showinfo("موفقیت", "گزارش با موفقیت ذخیره شد")
            except Exception as e:
                messagebox.showerror("خطا", f"خطا در ذخیره فایل: {str(e)}")

    def export_json(self):
        if not self.analyzer.mods:
            messagebox.showwarning("هشدار", "ابتدا ماد ها را تحلیل کنید")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="خروجی JSON"
        )
        
        if file_path:
            try:
                data = {
                    'analysis_date': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'directory_path': self.path_var.get(),
                    'total_mods': len(self.analyzer.mods),
                    'compatibility_score': self.analyzer.check_compatibility().get('overall', 0) * 100,
                    'hardware_requirements': self.analyzer.calculate_hardware_requirements(),
                    'mods': [
                        {
                            'name': mod.name,
                            'version': mod.version,
                            'mc_version': mod.mc_version,
                            'mod_loader': mod.mod_loader,
                            'mod_id': mod.mod_id,
                            'file_path': mod.file_path,
                            'size_mb': round(mod.size / (1024 * 1024), 2),
                            'dependencies': mod.dependencies,
                            'memory_usage_mb': mod.memory_usage,
                            'performance_impact': mod.performance_impact
                        }
                        for mod in self.analyzer.mods
                    ]
                }
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                messagebox.showinfo("موفقیت", "فایل JSON با موفقیت ذخیره شد")
            except Exception as e:
                messagebox.showerror("خطا", f"خطا در ذخیره فایل JSON: {str(e)}")

    def run(self):
        try:
            self.root.mainloop()
        except Exception as e:
            print(f"خطا در اجرای برنامه: {e}")

if __name__ == "__main__":
    try:
        app = ModAnalyzerGUI()
        app.run()
    except Exception as e:
        print(f"خطا در شروع برنامه: {e}")
        input("Press Enter to exit...")