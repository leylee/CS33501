/*
 * THIS FILE IS FOR IP FORWARD TEST
 */
#include "sysInclude.h"
#include <inttypes.h>

// system support
extern void fwd_LocalRcv(char *pBuffer, int length);

extern void fwd_SendtoLower(char *pBuffer, int length, unsigned int nexthop);

extern void fwd_DiscardPkt(char *pBuffer, int type);

extern unsigned int getIpv4Address();

// implemented by students

struct RouteNode {
    RouteNode *children[2];
    uint32_t nexthop;
    uint32_t fake_nexthop;
    bool is_leaf;
    bool is_fake_leaf;

    RouteNode()
    {
        children[0] = NULL;
        children[1] = NULL;
        is_leaf = false;
    }

    ~RouteNode()
    {
        if (children[0])
            delete children[0];
        if (children[1])
            delete children[1];
    }

    void add_route(const stud_route_msg *proute, int depth = 0)
    {
        // 大 端 序 转 小 端 序 ! ! !
        uint32_t dest = ntohl(proute->dest);

        if (depth == (proute->masklen >> 24)) { // 掩 码 长 度 也 要 转 ! ! !
            is_leaf = true;
            nexthop = proute->nexthop;
        } else {
            int bit = (dest >> (31 - depth)) & 0x1;
            if (children[bit] == NULL) {
                children[bit] = new RouteNode();
            }
            children[bit]->add_route(proute, depth + 1);
        }

        // 路由聚合
        if (is_leaf && children[0] == NULL && children[1] == NULL) {
            is_fake_leaf = true;
            fake_nexthop = nexthop;
        } else if (children[0] != NULL && children[1] != NULL &&
                   children[0]->nexthop == children[1]->nexthop) {
            is_fake_leaf = true;
            fake_nexthop = children[0]->nexthop;
        } else {
            is_fake_leaf = false;
        }
    }
};

uint16_t bytes_to_uint16(const uint8_t *bytes)
{
    return ((uint16_t)bytes[0] << 8) | bytes[1];
}

uint32_t bytes_to_uint32(const uint8_t *bytes)
{
    return ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16) | ((uint32_t)bytes[2] << 8) |
           bytes[3];
}

void uint16_to_bytes(uint8_t *bytes, uint16_t n)
{
    bytes[0] = n >> 8;
    bytes[1] = n;
}

uint16_t calc_checksum(const uint8_t *header, uint8_t header_length)
{
    uint32_t checksum = 0;
    int i;
    for (i = 0; i < header_length; i += 2) {
        if (i == 10)
            continue;
        checksum += bytes_to_uint16(header + i);
    }
    while (checksum > 0x0000FFFFu) {
        checksum = (checksum & 0xFFFF) + (checksum >> 16);
    }
    return ~(uint16_t)checksum;
}

RouteNode *route_tree;

void stud_Route_Init()
{
    route_tree = new RouteNode();
    return;
}

void stud_route_add(stud_route_msg *proute)
{
    route_tree->add_route(proute);
    return;
}

int stud_fwd_deal(char *pBuffer, int length)
{
    int error_type = STUD_IP_TEST_CORRECT;
    int nexthop;
    int checksum;
    RouteNode *cur;

    uint8_t ttl;
    uint32_t dest_addr;
    uint8_t *upBuffer = (uint8_t *)pBuffer;

    ttl = upBuffer[8];
    dest_addr = bytes_to_uint32(upBuffer + 16);

    if (ttl == 0) {
        error_type = STUD_IP_TEST_TTL_ERROR;
        goto error_handler;
    }
    if (dest_addr == getIpv4Address()) {
        error_type = STUD_FORWARD_TEST_LOCALHOST;
        fwd_LocalRcv(pBuffer, length);
        return 0;
    }

    upBuffer[8] = ttl - 1;
    if (ttl == 0) {
        error_type = STUD_FORWARD_TEST_TTLERROR;
        goto error_handler;
    }
    checksum = calc_checksum(upBuffer, 20);
    uint16_to_bytes(upBuffer + 10, checksum);

    cur = route_tree;
    for (int depth = 0; depth <= 32; ++depth) {
        if (cur->is_fake_leaf) {
            nexthop = cur->fake_nexthop;
            break;
        } else if (cur->is_leaf) {
            nexthop = cur->nexthop;
        }

        int bit = (dest_addr >> (31 - depth)) & 0x1;
        if (cur->children[bit] != NULL) {
            cur = cur->children[bit];
        } else {
            error_type = STUD_FORWARD_TEST_NOROUTE;
            goto error_handler;
        }
    }

    fwd_SendtoLower(pBuffer, length, nexthop);
    return 0;

error_handler:
    fwd_DiscardPkt(pBuffer, error_type);
    return 1;
}
