"""
Freeplane Mindmap Service
Mindmap dosyalarını oluşturma, okuma ve düzenleme işlemleri
"""
import freeplane
from typing import Optional
from io import BytesIO
import tempfile
import os
from app.utils.logging_config import mindmap_logger


class MindmapService:
    """Freeplane mindmap işlemleri için servis"""
    
    @staticmethod
    def create_empty_mindmap(root_text: str = "Yeni Mindmap") -> str:
        """Boş bir mindmap oluştur ve XML olarak döndür"""
        # Geçici dosya oluştur
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mm', delete=False) as f:
            # Minimal Freeplane XML yapısı
            xml_content = f'''<map version="freeplane 1.9.0">
<node TEXT="{root_text}" FOLDED="false" ID="ID_1">
</node>
</map>'''
            f.write(xml_content)
            temp_path = f.name
        
        try:
            # Freeplane ile aç ve düzgün formatta kaydet
            mm = freeplane.Mindmap(temp_path)
            mm.save(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content
        finally:
            os.unlink(temp_path)
    
    @staticmethod
    def parse_mindmap(content: str) -> dict:
        """Mindmap XML veya JSON içeriğini parse edip JSON yapısına çevir"""
        if not content:
            return {"id": "root", "text": "Yeni Mindmap", "children": []}
            
        # JSON kontrolü
        stripped_content = content.strip()
        if stripped_content.startswith('{'):
            import json
            try:
                data = json.loads(stripped_content)
                # MindElixir formatı mı?
                if "mindData" in data:
                    node = data["mindData"]["nodeData"]
                    return MindmapService._mindelixir_to_generic(node)
                return data
            except:
                pass

        with tempfile.NamedTemporaryFile(mode='w', suffix='.mm', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        
        try:
            mm = freeplane.Mindmap(temp_path)
            root = mm.root
            return MindmapService._node_to_dict(root)
        finally:
            os.unlink(temp_path)

    @staticmethod
    def _mindelixir_to_generic(node) -> dict:
        """MindElixir formatını projenin genel formatına çevir"""
        return {
            "id": node.get("id"),
            "text": node.get("topic", ""),
            "children": [MindmapService._mindelixir_to_generic(c) for c in node.get("children", [])]
        }

    
    @staticmethod
    def _node_to_dict(node) -> dict:
        """Freeplane node'unu dict'e çevir"""
        result = {
            "id": node.id,
            "text": node.plaintext or "",
            "children": []
        }
        
        # Attributes
        try:
            if hasattr(node, 'attributes') and node.attributes:
                result["attributes"] = dict(node.attributes)
        except:
            pass
        
        # Notes
        try:
            if hasattr(node, 'note') and node.note:
                result["note"] = node.note
        except:
            pass
        
        # Icons
        try:
            if hasattr(node, 'icons') and node.icons:
                result["icons"] = list(node.icons)
        except:
            pass
        
        # Children
        try:
            for child in node.children:
                result["children"].append(MindmapService._node_to_dict(child))
        except:
            pass
        
        return result
    
    @staticmethod
    def update_mindmap_from_json(content: str, json_data: dict) -> str:
        """JSON verisinden mindmap'i güncelle"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mm', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        
        try:
            mm = freeplane.Mindmap(temp_path)
            
            # Root node'u güncelle
            if "text" in json_data:
                mm.root.plaintext = json_data["text"]
            
            # Recursive olarak children'ları güncelle
            MindmapService._update_node_children(mm.root, json_data.get("children", []))
            
            mm.save(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                return f.read()
        finally:
            os.unlink(temp_path)
    
    @staticmethod
    def _update_node_children(parent_node, children_data: list):
        """Node children'larını güncelle"""
        existing_children = {child.id: child for child in parent_node.children}
        
        for child_data in children_data:
            child_id = child_data.get("id")
            
            if child_id and child_id in existing_children:
                # Mevcut node'u güncelle
                child = existing_children[child_id]
                if "text" in child_data:
                    child.plaintext = child_data["text"]
                
                # Recursive
                MindmapService._update_node_children(child, child_data.get("children", []))
            else:
                # Yeni node ekle
                try:
                    new_child = parent_node.add_child(child_data.get("text", "Yeni Düğüm"))
                    MindmapService._update_node_children(new_child, child_data.get("children", []))
                except:
                    pass
    
    @staticmethod
    def add_node(content: str, parent_id: str, text: str) -> tuple[str, dict]:
        """Belirtilen parent'a yeni node ekle"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mm', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        
        try:
            mm = freeplane.Mindmap(temp_path)
            
            # Parent node'u bul
            parent_nodes = mm.find_nodes(id=parent_id)
            if not parent_nodes:
                # Root'a ekle
                parent = mm.root
            else:
                parent = parent_nodes[0]
            
            # Yeni child ekle
            new_node = parent.add_child(text)
            
            mm.save(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                new_content = f.read()
            
            return new_content, {"id": new_node.id, "text": text}
        finally:
            os.unlink(temp_path)
    
    @staticmethod
    def update_node(content: str, node_id: str, text: str) -> str:
        """Node metnini güncelle"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mm', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        
        try:
            mm = freeplane.Mindmap(temp_path)
            
            nodes = mm.find_nodes(id=node_id)
            if nodes:
                nodes[0].plaintext = text
            
            mm.save(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                return f.read()
        finally:
            os.unlink(temp_path)
    
    @staticmethod
    def delete_node(content: str, node_id: str) -> str:
        """Node'u sil"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mm', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name
        
        try:
            mm = freeplane.Mindmap(temp_path)
            
            nodes = mm.find_nodes(id=node_id)
            if nodes and nodes[0] != mm.root:
                # Node'u parent'tan kaldır
                node = nodes[0]
                if hasattr(node, 'delete'):
                    node.delete()
            
            mm.save(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                return f.read()
        finally:
            os.unlink(temp_path)
