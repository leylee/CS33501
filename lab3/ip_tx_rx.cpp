/*
 * THIS FILE IS FOR IP TEST
 */
// system support
#include "sysInclude.h"
#include <inttypes.h>
#include <stdbool.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>
#define STUD_IP_TEST_UNKNOWN_ERROR -1

extern void ip_DiscardPkt(char *pBuffer, int type);

extern void ip_SendtoLower(char *pBuffer, int length);

extern void ip_SendtoUp(char *pBuffer, int length);

extern unsigned int getIpv4Address();

// implemented by students

void print_packet(const uint8_t *bytes, uint16_t length)
{
    int i;
    for (int i = 0; i < length; i++) {
        printf("%02x ", bytes[i]);
    }
    putchar('\n');
}

uint16_t bytes_to_uint16(const uint8_t *bytes)
{
    return ((uint16_t)bytes[0] << 8) | bytes[1];
}

uint32_t bytes_to_uint32(const uint8_t *bytes)
{
    return ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16) | ((uint32_t)bytes[2] << 8) |
           bytes[3];
}

void uint32_to_bytes(uint8_t *bytes, uint32_t n) {
	bytes[0] = n >> 24;
	bytes[1] = n >> 16;
	bytes[2] = n >> 8;
	bytes[3] = n;
}

void uint16_to_bytes(uint8_t *bytes, uint16_t n) {
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

int stud_ip_recv(char *pBuffer, unsigned short length)
{
    uint8_t *upBuffer = (uint8_t *)pBuffer;
    int error_type = STUD_IP_TEST_CORRECT;
    uint8_t version;
    uint8_t ihl;
    uint8_t dscp;
    uint16_t total_len;
    uint16_t id;
    uint8_t flags;
    bool df;
    bool mf;
    uint32_t offset;
    uint8_t ttl;
    uint8_t protocol;
    uint16_t checksum;
    uint32_t src_addr;
    uint32_t dest_addr;
    uint8_t *options;
    uint8_t *options_len;
    uint8_t *data;
    uint16_t data_len;

    // check length
    if (length < 20) {
        error_type = STUD_IP_TEST_UNKNOWN_ERROR;
        goto error_handler;
    }

    version = upBuffer[0] >> 4;
    ihl = (upBuffer[0] & 0x0F) << 2;
    dscp = upBuffer[1];
    total_len = bytes_to_uint16(upBuffer + 2);
    id = bytes_to_uint16(upBuffer + 4);
    flags = upBuffer[6] >> 5;
    df = flags & 0x02;
    mf = flags & 0x01;
    offset = (bytes_to_uint16(upBuffer + 6) & 0x1FFF) << 3;
    ttl = upBuffer[8];
    protocol = upBuffer[9];
    checksum = bytes_to_uint16(upBuffer + 10);
    src_addr = bytes_to_uint32(upBuffer + 12);
    dest_addr = bytes_to_uint32(upBuffer + 16);

    // check version
    if (version != 0x04) {
        error_type = STUD_IP_TEST_VERSION_ERROR;
        goto error_handler;
    }
    // check header length
    if (ihl < 20) {
        error_type = STUD_IP_TEST_HEADLEN_ERROR;
        goto error_handler;
    }
    // check length match
    if (total_len != length) {
        error_type = STUD_IP_TEST_UNKNOWN_ERROR;
        goto error_handler;
    }
    // check ttl
    if (ttl == 0) {
        error_type = STUD_IP_TEST_TTL_ERROR;
        goto error_handler;
    }
    // check checksum
    if (calc_checksum(upBuffer, ihl) != checksum) {
        error_type = STUD_IP_TEST_CHECKSUM_ERROR;
        goto error_handler;
    }
    // check dest ip addr
    if (getIpv4Address() != dest_addr) {
        error_type = STUD_IP_TEST_DESTINATION_ERROR;
        goto error_handler;
    }

    ip_SendtoUp(pBuffer + ihl, length - ihl);
    return 0;

error_handler:
    ip_DiscardPkt(pBuffer, error_type);
    return 1;
}

int stud_ip_Upsend(char *pBuffer, unsigned short len, unsigned int srcAddr, unsigned int dstAddr,
                   byte protocol, byte ttl)
{
	static bool sranded = false;
	if (!sranded) {
		srand(time(NULL));
	}
	uint8_t *buffer = (uint8_t *)malloc(len + 20);
	buffer[0] = 0x45;
	buffer[1] = 0x00;
	uint16_to_bytes(buffer + 2, len + 20);
	uint16_t random_id = (rand() << 8) | (rand() & 0xFF);
	uint16_to_bytes(buffer + 4, random_id);
	buffer[6] = 0x60;
	buffer[7] = 0x00;
	buffer[8] = ttl;
	buffer[9] = protocol;
	uint32_to_bytes(buffer + 12, srcAddr);
	uint32_to_bytes(buffer + 16, dstAddr);
	uint16_to_bytes(buffer + 10, calc_checksum(buffer, 20));
	memcpy(buffer + 20, pBuffer, len);

	ip_SendtoLower((char *)buffer, len + 20);
	free(buffer);
    return 0;
}
