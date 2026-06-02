#!/usr/bin/env python3
"""Manual endpoint testing to verify API works correctly."""
import asyncio
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import sys

# Test using TestClient to avoid actually starting server
try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import StoreEvent
    
    client = TestClient(app)
    
    STORE_ID = "STORE_BLR_002"
    
    def test_health():
        """Test health endpoint."""
        print("\n🏥 Testing GET /health")
        response = client.get("/health")
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Response: {json.dumps(data, indent=2)}")
        assert response.status_code == 200
        assert "status" in data
        print("   ✅ PASS")
        
    def test_ingest_and_metrics():
        """Test event ingest and metrics endpoints."""
        print("\n📨 Testing POST /events/ingest")
        
        # Create sample events
        base_time = datetime.now(timezone.utc)
        events = [
            {
                "event_id": str(uuid4()),
                "store_id": STORE_ID,
                "camera_id": "CAM_1",
                "visitor_id": "visitor_001",
                "event_type": "ENTRY",
                "timestamp": base_time.isoformat(),
                "zone_id": "ENTRY",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.95,
                "metadata": {}
            },
            {
                "event_id": str(uuid4()),
                "store_id": STORE_ID,
                "camera_id": "CAM_2",
                "visitor_id": "visitor_001",
                "event_type": "ZONE_ENTER",
                "timestamp": (base_time + timedelta(seconds=10)).isoformat(),
                "zone_id": "SKINCARE",
                "dwell_ms": 5000,
                "is_staff": False,
                "confidence": 0.92,
                "metadata": {}
            },
            {
                "event_id": str(uuid4()),
                "store_id": STORE_ID,
                "camera_id": "CAM_5",
                "visitor_id": "visitor_001",
                "event_type": "BILLING_QUEUE_JOIN",
                "timestamp": (base_time + timedelta(seconds=30)).isoformat(),
                "zone_id": "BILLING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.98,
                "metadata": {}
            }
        ]
        
        response = client.post("/events/ingest", json={"events": events})
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Accepted: {data['accepted']}, Duplicates: {data['duplicates']}, Rejected: {data['rejected']}")
        assert response.status_code == 200
        assert data["accepted"] >= 1
        print("   ✅ PASS")
        
    def test_metrics():
        """Test metrics endpoint."""
        print("\n📊 Testing GET /stores/{store_id}/metrics")
        response = client.get(f"/stores/{STORE_ID}/metrics")
        print(f"   Status: {response.status_code}")
        data = response.json()
        required_fields = ["unique_visitors", "conversion_rate", "queue_depth", "abandonment_rate"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
            print(f"   {field}: {data[field]}")
        assert response.status_code == 200
        print("   ✅ PASS")
        
    def test_funnel():
        """Test funnel endpoint."""
        print("\n🔗 Testing GET /stores/{store_id}/funnel")
        response = client.get(f"/stores/{STORE_ID}/funnel")
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Stages: {len(data['stages'])}")
        for stage in data["stages"]:
            drop_off = stage.get('drop_off_pct', 'N/A')
            print(f"     - {stage['stage']}: count={stage['count']}, drop_off_pct={drop_off}")
        assert response.status_code == 200
        assert "stages" in data
        print("   ✅ PASS")
        
    def test_heatmap():
        """Test heatmap endpoint."""
        print("\n🗺️  Testing GET /stores/{store_id}/heatmap")
        response = client.get(f"/stores/{STORE_ID}/heatmap")
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Confidence: {data['data_confidence']}")
        print(f"   Zones: {len(data['zones'])} (may be 0 if no zone events)")
        assert response.status_code == 200
        assert "data_confidence" in data
        print("   ✅ PASS")
        
    def test_anomalies():
        """Test anomalies endpoint."""
        print("\n⚠️  Testing GET /stores/{store_id}/anomalies")
        response = client.get(f"/stores/{STORE_ID}/anomalies")
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Active anomalies: {len(data['active_anomalies'])}")
        assert response.status_code == 200
        assert "active_anomalies" in data
        print("   ✅ PASS")
        
    # Run tests
    print("=" * 60)
    print("🚀 MANUAL ENDPOINT TESTS")
    print("=" * 60)
    
    try:
        test_health()
        test_ingest_and_metrics()
        test_metrics()
        test_funnel()
        test_heatmap()
        test_anomalies()
        
        print("\n" + "=" * 60)
        print("✅ ALL ENDPOINT TESTS PASSED!")
        print("=" * 60)
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure to run from project root with proper PYTHONPATH")
    sys.exit(1)
