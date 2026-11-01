# Development variant of www/beryllium: the same build under a separate
# package name, so a development build can never be mistaken for the
# production package (plan/01 D5). In Phase 2 it will also keep the debug
# switches and the attacker payload hook (plan/12 section 6.1) that the
# production build compiles out.

PKGNAMESUFFIX=	-devel
COMMENT=	Privacy-focused Chromium-based web browser (development build)
CONFLICTS_INSTALL=	beryllium

MASTERDIR=	${.CURDIR}/../beryllium

.include "${MASTERDIR}/Makefile"
