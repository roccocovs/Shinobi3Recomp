#include "genesis_runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

M68KState g_cpu;
uint8_t g_rom[0x400000], g_ram[0x10000];
int g_split_sp_popped, rte;
int *g_rte_pending_ptr=&rte;
uint32_t g_r4_scroll_trace_current_pc, g_cycle_accumulator, g_audio_cycle_counter;
uint32_t g_vblank_threshold=0xFFFFFFFFu;
uint64_t g_native_insn_count;
static uint32_t objects[512], ship;
static unsigned allocated, particles, missing, calls, ctrl_writes, data_writes;
static uint16_t last_data;
static int broken;
/* GENERATED_DECLARATIONS */
static void need(int ok,const char *message) {
    if (!ok) { fprintf(stderr,"FAIL: %s PC=$%06X SP=$%08X\n",message,
                        g_r4_scroll_trace_current_pc,g_cpu.A[7]); exit(1); }
}
uint8_t m68k_read8(uint32_t a) {
    a&=0xFFFFFFu;
    if(a>=0xFF0000u) return g_ram[a&0xFFFFu];
    need(a<sizeof(g_rom),"unexpected fixture memory read"); return g_rom[a];
}
uint16_t m68k_read16(uint32_t a) {return (m68k_read8(a)<<8)|m68k_read8(a+1);}
uint32_t m68k_read32(uint32_t a) {return ((uint32_t)m68k_read16(a)<<16)|m68k_read16(a+2);}
void m68k_write8(uint32_t a,uint8_t v) {need((a&0xFFFFFFu)>=0xFF0000u,"unexpected byte write");g_ram[a&0xFFFFu]=v;}
void m68k_write16(uint32_t a,uint16_t v) {
    if((a&0xFFFFFFu)==0xC00000u) {++data_writes;last_data=v;return;}
    if((a&0xFFFFFFu)==0xC00004u || (a&0xFFFFFFu)==0xC00006u) {++ctrl_writes;return;}
    m68k_write8(a,v>>8);m68k_write8(a+1,v);
}
void m68k_write32(uint32_t a,uint32_t v) {m68k_write16(a,v>>16);m68k_write16(a+2,v);}
void glue_check_vblank(void) {need(0,"fixture unexpectedly reached cycle ceiling");}
void recomp_push_return(uint32_t pc) {g_cpu.A[7]-=4;m68k_write32(g_cpu.A[7],pc);}

/* Allocation is a controlled fixture input; original $00178E initializes
 * its live object/type/state. It does not replace production allocation. */
static void allocate(void) {
    need(allocated<512,"fixture pool exhausted");
    g_cpu.A[6]=0xFF4000u+allocated*0x60u;
    objects[allocated++]=g_cpu.A[6];
    func_00178E();
}
void func_001712(void) {allocate();ship=g_cpu.A[6];}
void func_0016F0(void) {allocate();++particles;}
void func_0096EE(void) {g_cpu.D[0]=0;g_cpu.SR|=SR_Z;}
void func_0094A0(void) {g_cpu.D[0]=g_cpu.D[1]=0;}
void func_036716(void) {m68k_write16(g_cpu.A[0],0);}

typedef struct Tail {int pending;uint32_t addr;struct Tail *prev;} Tail;
static Tail *tail;
static RecompFuncPtr lookup(uint32_t addr) {
    switch(addr) {
    case 0x036716:return func_036716;
    /* GENERATED_LOOKUP */
    default:return NULL;
    }
}
void recomp_tail_call(uint32_t addr) {need(tail!=NULL,"tail without frame");tail->pending=1;tail->addr=addr;}
void recomp_call_func(RecompFuncPtr fn) {
    Tail f={0,0,tail};tail=&f;
    need(++calls<100000,"nonreturning fixture execution");fn();
    while(f.pending) {uint32_t pc=f.addr;f.pending=0;recomp_call_addr(pc);if(rte)break;}
    tail=f.prev;
}
void recomp_call_addr(uint32_t addr) {
    RecompFuncPtr fn=lookup(addr);
    if(broken && addr==0x107F2u) fn=NULL;
    if(!fn) {
        if(!missing && !broken)fprintf(stderr,"fixture missing dependency $%06X at $%06X\n",addr,g_r4_scroll_trace_current_pc);
        ++missing;return;
    } recomp_call_func(fn);
}
void hybrid_jmp_interpret(uint32_t addr) {recomp_call_addr(addr);}

static void invoke(uint32_t addr) {
    uint32_t sp=g_cpu.A[7];recomp_push_return(0x123456u);
    uint32_t slot=g_cpu.A[7];recomp_call_addr(addr);
    need(!rte,"unexpected unwind");
    need(g_cpu.A[7]==slot,"callback changed caller stack");
    if(m68k_read32(slot)!=0x123456u) {
        fprintf(stderr,"entry=$%06X return slot=$%08X actual=$%08X allocations=%u\n",
                addr,slot,m68k_read32(slot),allocated);
        need(0,"callback changed return address");
    }
    g_cpu.A[7]=sp;
}
static void run_crash(int omit_callback) {
    memset(g_ram,0,sizeof(g_ram));memset(&g_cpu,0,sizeof(g_cpu));
    broken=omit_callback;allocated=particles=missing=calls=0;ship=0;rte=0;
    g_split_sp_popped=0;g_cpu.A[7]=0xFFFF00u;g_cpu.SR=0x2300;
    m68k_write16(0xFF0034,8);
    m68k_write32(0xFF00F8,0xFFB00000u); /* original $0104EC scene setup */
    unsigned frames;
    for(frames=0;frames<1000 && m68k_read16(0xFF0034)!=0x48;frames++) invoke(0x10548);
    need(ship && frames==256,"original scroll condition did not spawn ship");
    need(m68k_read16(ship+2)==0x100,"allocator did not select table index $0100");
    need(m68k_read32(0xFF00F8)==ship,"scene lost spawned object pointer");
    need(m68k_read16(ship+0x20)==0x90 && m68k_read16(ship+0x24)==0,
         "original ship position not produced");
    for(frames=0;frames<600;frames++) {
        m68k_write16(0xFF0022,(uint16_t)frames);
        uint16_t state=m68k_read16(0xFF0034);
        if(state==0x48) invoke(0x109D0);
        else if(state==0xC) {
            int ready=m68k_read16(ship+0x24)>=0x70;
            invoke(0x10568);
            need(ready==(m68k_read16(0xFF0034)==0x48),"Y completion gate diverged");
            if(ready)break;
        } else need(0,"unexpected crash timeline state");
        unsigned active=allocated;
        for(unsigned i=0;i<active;i++) {
            if(!(m68k_read16(objects[i])&0x8000u))continue;
            g_cpu.A[0]=objects[i];
            uint32_t cb=m68k_read32(0x365A2u+m68k_read16(objects[i]+2));
            need(cb==0x107F2u,"unexpected fixture object handler");invoke(cb);
        }
        active=allocated;
        for(unsigned i=0;i<active;i++) {
            if(!(m68k_read16(objects[i])&0x8000u))continue;
            g_cpu.A[0]=objects[i];invoke(0x19D4);
        }
    }
    need(frames==448,"ship velocity did not reach ROM Y threshold after 448 updates");
    need(m68k_read16(0xFF0036)==0xC,"crash completion did not enter authentic timed transition");
    if(omit_callback) {
        need(missing>0 && particles==0,"pre-fix missing callback was not reproduced");
        puts("PASS: pre-fix callback omission suppresses crash particles; alone it does not stall ship movement");
    } else {
        need(missing==0,"native crash path has an unrepresented dependency");
        need(particles>0,"native crash animation produced no particles");
        puts("PASS: generated ship spawn, animation/particles, Y completion and balanced returns");
    }
}
int main(int argc,char **argv) {
    need(argc==2,"ROM argument");FILE *f=fopen(argv[1],"rb");need(f!=NULL,"read ROM");
    need(fread(g_rom,1,0x200000,f)>0,"empty ROM");fclose(f);
    run_crash(0);run_crash(1);
    /* Real generated interrupt body: it preserves every D/A register, writes
     * the raster scroll value, and consumes exactly the SR/PC exception frame. */
    broken=0;rte=0;g_split_sp_popped=0;calls=0;ctrl_writes=data_writes=0;
    for(unsigned i=0;i<8;i++){g_cpu.D[i]=0x11220000u+i;g_cpu.A[i]=0xFF6000u+i*16;}
    g_cpu.A[7]=0xFFEE00u;m68k_write16(g_cpu.A[7],0x2300);m68k_write32(g_cpu.A[7]+2,0x123456u);
    m68k_write16(0xFF00FC,0x015A);M68KState saved=g_cpu;
    recomp_call_addr(0x10A02);
    need(rte==1 && g_cpu.PC==0x123456u && g_cpu.SR==0x2300 && g_cpu.A[7]==saved.A[7]+6,
         "HBlank did not restore exact exception frame");
    need(!memcmp(g_cpu.D,saved.D,sizeof(saved.D)) && !memcmp(g_cpu.A,saved.A,7*sizeof(uint32_t)),
         "HBlank changed interrupted registers");
    need(ctrl_writes==2 && data_writes==1 && last_data==0x015A,"HBlank raster transfer changed");
    puts("PASS: ending HBlank native register preservation, VSRAM write and RTE frame");return 0;
}
