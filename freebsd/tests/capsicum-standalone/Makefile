# Builds with FreeBSD make or GNU make.
CC ?= cc
CFLAGS ?= -O2 -g
WARNS = -Wall -Wextra -Wno-unused-parameter

cap-oracle: cap-oracle.c
	$(CC) $(CFLAGS) $(WARNS) -o cap-oracle cap-oracle.c

clean:
	rm -f cap-oracle
