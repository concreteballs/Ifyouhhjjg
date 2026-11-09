import tempfile
import unittest
from pathlib import Path
from spectral_core import (
    ControlPlane, Packet, PacketType, Router, SpectralAddress,
    SpectralDatabase, SpectralNetwork, SpectralRuntime,
)


class RoutingControlTests(unittest.TestCase):
    def make_network(self):
        network = SpectralNetwork()
        for rid, pos in [("r0",(0,0)),("r1",(1,0)),("r2",(0,1)),("r3",(1,1))]:
            network.add_router(Router(rid,pos))
        network.connect("r0","r1")
        network.connect("r1","r3")
        network.connect("r0","r2")
        network.connect("r2","r3")
        source, destination = SpectralAddress("123"), SpectralAddress("987")
        network.register_endpoint(source,"r0")
        network.register_endpoint(destination,"r3")
        return network, source, destination

    def test_tail_first_responsibility_uses_longest_prefix(self):
        network, _, destination = self.make_network()
        network.assign_responsibility("r2","7")
        network.assign_responsibility("r1","78")
        self.assertEqual(destination.tail_first,"789")
        self.assertEqual(network.responsibility_owner(destination),"r1")

    def test_bad_local_hint_generates_bounded_correction(self):
        network, source, destination = self.make_network()
        network.set_route_hint("r0","789","r2")
        db = SpectralDatabase()
        try:
            runtime = SpectralRuntime(network,db)
            route = runtime.route(Packet(source,destination,b"x"))
            self.assertEqual(route,["r0","r1","r3"])
            events = [e for e in runtime.monitor.events() if e["event"]=="route_correction"]
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]["data"]["rejected_next_hop"],"r2")
            self.assertEqual(events[0]["data"]["corrected_next_hop"],"r1")
        finally:
            db.close()

    def test_neighbour_assistance_routes_around_failed_node(self):
        network, _, _ = self.make_network()
        path = network.neighbour_assistance("r1","r0","r3")
        self.assertEqual(path,["r0","r2","r3"])

    def test_authenticated_detour_is_one_use(self):
        network, source, destination = self.make_network()
        db = SpectralDatabase()
        control = ControlPlane(b"x"*32)
        runtime = SpectralRuntime(network,db,control_plane=control)
        try:
            packet = Packet(source,destination,b"detour",packet_type=PacketType.DETOUR)
            authorization = control.authorize_detour(packet.packet_id,["r0","r2","r3"])
            self.assertEqual(runtime.send(packet,authorization),["r0","r2","r3"])
            with self.assertRaises(PermissionError):
                runtime.send(packet,authorization)
        finally:
            db.close()

    def test_unsigned_detour_is_rejected(self):
        network, source, destination = self.make_network()
        db = SpectralDatabase()
        runtime = SpectralRuntime(network,db,control_plane=ControlPlane(b"y"*32))
        try:
            packet = Packet(source,destination,b"no",packet_type=PacketType.DETOUR)
            with self.assertRaises(PermissionError):
                runtime.send(packet)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
