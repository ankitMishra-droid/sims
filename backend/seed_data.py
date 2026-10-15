"""
Database Seeding Script for StockSangati Smart Inventory Management System
Populates initial suppliers and ~20 realistic inventory products with complete details.
"""

import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal, engine, base
from app import models

# List of realistic suppliers
SUPPLIERS_DATA = [
    {
        "name": "Nexus Distribution Hub",
        "contact_person": "Sarah Jenkins",
        "email": "s.jenkins@nexusdist.com",
        "phone": "+1-555-014-9922",
        "address": "450 Logistics Blvd, Dock 12, Chicago, IL 60607",
        "lead_time_days": 5,
        "is_active": True,
    },
    {
        "name": "Apex Tech Solutions",
        "contact_person": "Alex Vance",
        "email": "alex.vance@apextech.com",
        "phone": "+1-555-019-2831",
        "address": "100 Innovation Way, Suite 400, San Jose, CA 95134",
        "lead_time_days": 4,
        "is_active": True,
    },
    {
        "name": "Optima Office Essentials",
        "contact_person": "David Miller",
        "email": "dmiller@optimaoffice.com",
        "phone": "+1-555-018-7733",
        "address": "782 Commerce Parkway, Atlanta, GA 30318",
        "lead_time_days": 3,
        "is_active": True,
    },
    {
        "name": "Quantum Component Labs",
        "contact_person": "Elena Rostova",
        "email": "elena@quantumlabs.io",
        "phone": "+1-555-012-4455",
        "address": "220 Silicon Park Dr, Austin, TX 78701",
        "lead_time_days": 7,
        "is_active": True,
    },
    {
        "name": "CyberCore Network Gear",
        "contact_person": "Lisa Chen",
        "email": "lchen@cybercoregear.com",
        "phone": "+1-555-017-3366",
        "address": "350 Fiber Optics Way, Seattle, WA 98101",
        "lead_time_days": 6,
        "is_active": True,
    },
    {
        "name": "Vertex Workspace & Ergonomics",
        "contact_person": "Marcus Brody",
        "email": "marcus.b@vertexergonomics.com",
        "phone": "+1-555-016-8811",
        "address": "910 Industrial Loop, Grand Rapids, MI 49503",
        "lead_time_days": 8,
        "is_active": True,
    },
]

# 21 realistic products categorized and mapped to suppliers
PRODUCTS_DATA = [
    # Electronics / Laptops
    {
        "sku": "LAP-APL-M3P14",
        "name": "MacBook Pro 14\" (Apple M3 Pro, 18GB RAM, 512GB SSD)",
        "category": "Electronics",
        "unit": "piece",
        "cost_price": 1550.00,
        "selling_price": 1999.00,
        "current_stock": 24,
        "reorder_level": 8,
        "supplier_name": "Nexus Distribution Hub",
    },
    {
        "sku": "LAP-DEL-XPS15",
        "name": "Dell XPS 15 9530 (Intel Core i7, 32GB RAM, 1TB SSD)",
        "category": "Electronics",
        "unit": "piece",
        "cost_price": 1420.00,
        "selling_price": 1849.00,
        "current_stock": 18,
        "reorder_level": 6,
        "supplier_name": "Nexus Distribution Hub",
    },
    {
        "sku": "LAP-LEN-X1C11",
        "name": "Lenovo ThinkPad X1 Carbon Gen 11 (16GB RAM, 512GB SSD)",
        "category": "Electronics",
        "unit": "piece",
        "cost_price": 1180.00,
        "selling_price": 1499.00,
        "current_stock": 15,
        "reorder_level": 5,
        "supplier_name": "Nexus Distribution Hub",
    },

    # Audio & Visual
    {
        "sku": "DIS-LG-27UP850",
        "name": "LG UltraFine 27\" 4K UHD IPS USB-C Monitor",
        "category": "Audio & Visual",
        "unit": "piece",
        "cost_price": 310.00,
        "selling_price": 449.00,
        "current_stock": 35,
        "reorder_level": 10,
        "supplier_name": "Apex Tech Solutions",
    },
    {
        "sku": "DIS-DEL-U3423WE",
        "name": "Dell UltraSharp 34\" Curved WQHD USB-C Hub Monitor",
        "category": "Audio & Visual",
        "unit": "piece",
        "cost_price": 590.00,
        "selling_price": 799.00,
        "current_stock": 12,
        "reorder_level": 4,
        "supplier_name": "Apex Tech Solutions",
    },
    {
        "sku": "AUD-SNY-WH1000M5",
        "name": "Sony WH-1000XM5 Wireless Noise-Canceling Headphones",
        "category": "Audio & Visual",
        "unit": "piece",
        "cost_price": 260.00,
        "selling_price": 398.00,
        "current_stock": 42,
        "reorder_level": 12,
        "supplier_name": "Apex Tech Solutions",
    },
    {
        "sku": "AUD-JAB-EV275",
        "name": "Jabra Evolve2 75 Wireless Headset with Mic Boom",
        "category": "Audio & Visual",
        "unit": "piece",
        "cost_price": 195.00,
        "selling_price": 299.00,
        "current_stock": 28,
        "reorder_level": 8,
        "supplier_name": "Apex Tech Solutions",
    },

    # Computer Accessories
    {
        "sku": "ACC-LOG-MXM3S",
        "name": "Logitech MX Master 3S Performance Wireless Mouse",
        "category": "Computer Accessories",
        "unit": "piece",
        "cost_price": 68.00,
        "selling_price": 99.99,
        "current_stock": 85,
        "reorder_level": 20,
        "supplier_name": "Optima Office Essentials",
    },
    {
        "sku": "ACC-LOG-MXKEY",
        "name": "Logitech MX Keys S Wireless Illuminated Keyboard",
        "category": "Computer Accessories",
        "unit": "piece",
        "cost_price": 76.00,
        "selling_price": 119.99,
        "current_stock": 64,
        "reorder_level": 15,
        "supplier_name": "Optima Office Essentials",
    },
    {
        "sku": "ACC-CAL-TS4",
        "name": "CalDigit TS4 Thunderbolt 4 18-Port Docking Station",
        "category": "Computer Accessories",
        "unit": "piece",
        "cost_price": 285.00,
        "selling_price": 399.95,
        "current_stock": 22,
        "reorder_level": 6,
        "supplier_name": "Optima Office Essentials",
    },
    {
        "sku": "ACC-ANK-737",
        "name": "Anker 737 Power Bank (PowerCore 24K, 140W Fast Charge)",
        "category": "Computer Accessories",
        "unit": "piece",
        "cost_price": 85.00,
        "selling_price": 139.99,
        "current_stock": 45,
        "reorder_level": 12,
        "supplier_name": "Optima Office Essentials",
    },

    # Networking
    {
        "sku": "NET-CIS-C9200L",
        "name": "Cisco Catalyst 9200L 24-Port Gigabit PoE+ Managed Switch",
        "category": "Networking",
        "unit": "piece",
        "cost_price": 1450.00,
        "selling_price": 1890.00,
        "current_stock": 7,
        "reorder_level": 3,
        "supplier_name": "CyberCore Network Gear",
    },
    {
        "sku": "NET-UBNT-U6PRO",
        "name": "Ubiquiti UniFi 6 Pro Dual-Band WiFi 6 Access Point",
        "category": "Networking",
        "unit": "piece",
        "cost_price": 110.00,
        "selling_price": 159.00,
        "current_stock": 50,
        "reorder_level": 15,
        "supplier_name": "CyberCore Network Gear",
    },
    {
        "sku": "NET-FTN-FG60F",
        "name": "Fortinet FortiGate 60F Hardware Firewall Appliance",
        "category": "Networking",
        "unit": "piece",
        "cost_price": 530.00,
        "selling_price": 745.00,
        "current_stock": 14,
        "reorder_level": 4,
        "supplier_name": "CyberCore Network Gear",
    },
    {
        "sku": "NET-CAB-CAT6-1K",
        "name": "TrueCable Cat6 1000ft Solid UTP Bulk Ethernet Spool",
        "category": "Networking",
        "unit": "box",
        "cost_price": 98.00,
        "selling_price": 155.00,
        "current_stock": 32,
        "reorder_level": 10,
        "supplier_name": "CyberCore Network Gear",
    },

    # Storage & Memory
    {
        "sku": "STR-SAM-990P2T",
        "name": "Samsung 990 PRO 2TB NVMe M.2 Internal SSD",
        "category": "Storage & Memory",
        "unit": "piece",
        "cost_price": 120.00,
        "selling_price": 179.99,
        "current_stock": 58,
        "reorder_level": 16,
        "supplier_name": "Quantum Component Labs",
    },
    {
        "sku": "STR-CRU-64G56",
        "name": "Crucial Pro 64GB (2x32GB) DDR5 5600MHz Desktop RAM Kit",
        "category": "Storage & Memory",
        "unit": "box",
        "cost_price": 135.00,
        "selling_price": 189.99,
        "current_stock": 36,
        "reorder_level": 10,
        "supplier_name": "Quantum Component Labs",
    },
    {
        "sku": "STR-SYN-DS923P",
        "name": "Synology DiskStation DS923+ 4-Bay Network Attached Storage",
        "category": "Storage & Memory",
        "unit": "piece",
        "cost_price": 440.00,
        "selling_price": 599.99,
        "current_stock": 11,
        "reorder_level": 4,
        "supplier_name": "Quantum Component Labs",
    },

    # Office Furniture
    {
        "sku": "FUR-HM-AERON-B",
        "name": "Herman Miller Aeron Chair (Size B, Fully Loaded Graphite)",
        "category": "Office Furniture",
        "unit": "piece",
        "cost_price": 890.00,
        "selling_price": 1395.00,
        "current_stock": 16,
        "reorder_level": 5,
        "supplier_name": "Vertex Workspace & Ergonomics",
    },
    {
        "sku": "FUR-UPL-V2-60",
        "name": "Uplift V2 Standing Desk 60\" x 30\" (Bamboo Top, Black Frame)",
        "category": "Office Furniture",
        "unit": "piece",
        "cost_price": 490.00,
        "selling_price": 769.00,
        "current_stock": 15,
        "reorder_level": 4,
        "supplier_name": "Vertex Workspace & Ergonomics",
    },
    {
        "sku": "FUR-ERG-LXDUAL",
        "name": "Ergotron LX Dual Side-by-Side Stacking Monitor Arm",
        "category": "Office Furniture",
        "unit": "piece",
        "cost_price": 210.00,
        "selling_price": 329.00,
        "current_stock": 4,  # Notice: below reorder level (4 < 8) to trigger low stock alerts!
        "reorder_level": 8,
        "supplier_name": "Vertex Workspace & Ergonomics",
    },
]


def seed_database():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("[INFO] Initializing database tables...")
    base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. Seed or retrieve Suppliers
        print("\n[SUPPLIERS] Seeding Suppliers...")
        supplier_map = {}
        for s_data in SUPPLIERS_DATA:
            supplier = db.query(models.Supplier).filter(
                (models.Supplier.name == s_data["name"]) | (models.Supplier.email == s_data["email"])
            ).first()

            if not supplier:
                supplier = models.Supplier(**s_data)
                db.add(supplier)
                db.commit()
                db.refresh(supplier)
                print(f"  + Added Supplier: {supplier.name} (ID: {supplier.id})")
            else:
                print(f"  * Existing Supplier: {supplier.name} (ID: {supplier.id})")

            supplier_map[supplier.name] = supplier.id

        # 2. Seed Products
        print(f"\n[PRODUCTS] Seeding {len(PRODUCTS_DATA)} Products...")
        added_count = 0
        updated_count = 0

        for p_data in PRODUCTS_DATA:
            p_copy = dict(p_data)
            s_name = p_copy.pop("supplier_name", None)
            supplier_id = supplier_map.get(s_name)

            product = db.query(models.Product).filter(models.Product.sku == p_copy["sku"]).first()

            if not product:
                product = models.Product(
                    **p_copy,
                    supplier_id=supplier_id,
                    is_active=True
                )
                db.add(product)
                db.commit()
                db.refresh(product)
                added_count += 1
                print(f"  + Added Product [{product.sku}]: {product.name} ({product.category})")

                # Create initial inventory log
                if product.current_stock > 0:
                    log = models.InventoryLog(
                        product_id=product.id,
                        stock_in=product.current_stock,
                        stock_out=0,
                        closing_stock=product.current_stock,
                        reason="initial_stock"
                    )
                    db.add(log)
                    db.commit()
            else:
                # Update attributes to make sure category and supplier match
                for key, val in p_copy.items():
                    setattr(product, key, val)
                product.supplier_id = supplier_id
                product.is_active = True
                db.commit()
                updated_count += 1
                print(f"  * Updated Product [{product.sku}]: {product.name}")

        total_prods = db.query(models.Product).filter(models.Product.is_active == True).count()
        total_supps = db.query(models.Supplier).filter(models.Supplier.is_active == True).count()
        print(f"\n[SUCCESS] Seeding complete!")
        print(f"   Total Active Suppliers: {total_supps}")
        print(f"   Total Active Products:  {total_prods}")
        print(f"   (New: {added_count}, Existing/Updated: {updated_count})")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error during seeding: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
