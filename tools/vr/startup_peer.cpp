// SPDX-License-Identifier: GPL-2.0-only
// Transport-only probe: it deliberately never sends a Duke protocol packet.
#define UNREFERENCED_PARAMETER(parameter) (void)(parameter)
#define ENET_IMPLEMENTATION
#include "enet.h"

#include <cstdio>
#include <cstdlib>

int main(int argc, char **argv)
{
    if (argc != 2) return 64;
    ENetAddress address{};
    char loopback[]="127.0.0.1";
    address.port=static_cast<enet_uint16>(std::strtoul(argv[1],nullptr,10));
    if (enet_initialize() || !address.port || enet_address_set_host(&address,loopback))
    {
        std::puts("transport-setup-failed");
        return 65;
    }
    ENetHost *host=enet_host_create(nullptr,1,4,0,0);
    ENetPeer *peer=host ? enet_host_connect(host,&address,4,0) : nullptr;
    ENetEvent event{};
    bool connected=false;
    int const service=peer ? enet_host_service(host,&event,5000) : -1;
    std::printf("transport-service=%d event=%d\n", service, int(event.type));
    if (service > 0 && event.type == ENET_EVENT_TYPE_CONNECT)
    {
        connected=true;
        std::puts("transport-connected");
        enet_peer_disconnect_now(peer,0);
        std::puts("transport-disconnected-before-admission");
    }
    if (host) enet_host_destroy(host);
    enet_deinitialize();
    return connected ? 0 : 1;
}
