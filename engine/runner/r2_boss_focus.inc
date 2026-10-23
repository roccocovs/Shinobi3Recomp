/* Focused, opt-in Round 2 manager lifecycle capture. Included by reverse_debug.c. */
enum {
    R2F_CANDIDATE=1, R2F_ALLOC_RESULT, R2F_ROOT_CONFIRM, R2F_ROOT_CHANGE,
    R2F_FIELD_WRITE, R2F_MANAGER_TRANSITION, R2F_MANAGER_SAMPLE,
    R2F_MANAGER_HANDLER, R2F_POOL_DISPATCH, R2F_ANIMATION, R2F_MAP_SOURCE,
    R2F_MAP_VALUE, R2F_MAP_WRITE,
    R2F_RENDER_ENTRY, R2F_RENDER_HIDE, R2F_RENDER_MAP, R2F_RENDER_DESC,
    R2F_CULL, R2F_SPRITE_EMIT, R2F_STAGE_WRITE
};

static const char *r2f_name(uint8_t k)
{
    switch (k) {
    case R2F_CANDIDATE: return "candidate";
    case R2F_ALLOC_RESULT: return "allocator_result";
    case R2F_ROOT_CONFIRM: return "manager_root_confirm";
    case R2F_ROOT_CHANGE: return "manager_root_change";
    case R2F_FIELD_WRITE: return "object_field_write";
    case R2F_MANAGER_TRANSITION: return "manager_transition";
    case R2F_MANAGER_SAMPLE: return "manager_sample";
    case R2F_MANAGER_HANDLER: return "manager_handler";
    case R2F_POOL_DISPATCH: return "pool_dispatch";
    case R2F_ANIMATION: return "animation_dispatch";
    case R2F_MAP_SOURCE: return "animation_map_source";
    case R2F_MAP_VALUE: return "animation_map_value";
    case R2F_MAP_WRITE: return "animation_map_write";
    case R2F_RENDER_ENTRY: return "renderer_object";
    case R2F_RENDER_HIDE: return "renderer_hide_test";
    case R2F_RENDER_MAP: return "renderer_map";
    case R2F_RENDER_DESC: return "renderer_descriptor";
    case R2F_CULL: return "renderer_cull";
    case R2F_SPRITE_EMIT: return "sprite_emit";
    case R2F_STAGE_WRITE: return "sprite_staging_write";
    default: return "unknown";
    }
}

static void r2f_frame(uint32_t frame)
{
    if (!s_boss_diag.have_frame) s_boss_diag.first_frame = frame;
    if (s_boss_diag.have_frame && frame < s_boss_diag.last_frame) {
        s_boss_diag.timeline_epoch++;
        s_boss_diag.frame_regressions++;
    }
    s_boss_diag.last_frame = frame;
    s_boss_diag.have_frame = 1;
}

static void r2f_snapshot(uint32_t p, RdbBossFocusObject *o)
{
    memset(o, 0, sizeof(*o));
    if (!p) return;
    o->active=rdb_boss_read16(p);       o->type=rdb_boss_read16(p+2);
    o->state=rdb_boss_read16(p+4);       o->word08=rdb_boss_read16(p+8);
    o->map=rdb_boss_read16(p+0xA);      o->x=rdb_boss_read16(p+0xC);
    o->y=rdb_boss_read16(p+0xE);        o->vx=rdb_boss_read16(p+0x10);
    o->vy=rdb_boss_read16(p+0x12);      o->cursor=rdb_boss_read16(p+0x28);
    o->anim2a=rdb_boss_read16(p+0x2A);  o->timer2c=rdb_boss_read16(p+0x2C);
    o->word2e=rdb_boss_read16(p+0x2E);  o->word30=rdb_boss_read16(p+0x30);
    o->word32=rdb_boss_read16(p+0x32);  o->word34=rdb_boss_read16(p+0x34);
    o->word38=rdb_boss_read16(p+0x38);  o->word3a=rdb_boss_read16(p+0x3A);
    o->word3c=rdb_boss_read16(p+0x3C);  o->word3e=rdb_boss_read16(p+0x3E);
    o->word40=rdb_boss_read16(p+0x40);  o->word42=rdb_boss_read16(p+0x42);
    o->word44=rdb_boss_read16(p+0x44);  o->callback=rdb_boss_read32(p+0x48);
    o->link=rdb_boss_read32(p+0x50);
}

static void r2f_emit(uint8_t kind, uint32_t p, uint32_t addr,
                     uint32_t before, uint32_t after, uint8_t field,
                     int preserve)
{
    RdbBossFocusEvent e;
    memset(&e, 0, sizeof(e));
    e.seq=++s_boss_diag.seq; e.frame=cmd_server_current_frame();
    r2f_frame(e.frame); e.epoch=s_boss_diag.timeline_epoch;
    e.pc=g_rdb_boss_diag_pc&0xFFFFFFu;
    e.func=g_rdb_current_func&0xFFFFFFu;
    e.raw_manager=rdb_boss_read32(0xFF5EE6u);
    e.manager=s_boss_diag.focus_manager
        ? s_boss_diag.focus_manager : rdb_boss_normalize_object(e.raw_manager);
    e.object_ptr=rdb_boss_normalize_object(p);
    e.addr=addr&0xFFFFFFu; e.before=before; e.after=after;
    e.value=(uint8_t)after; e.field=field; e.stage=rdb_boss_read8(0xFF37A6u);
    e.kind=kind;
    for (unsigned i=0;i<8;i++) { e.d[i]=g_cpu.D[i]; e.a[i]=g_cpu.A[i]; }
    e.sr=g_cpu.SR; r2f_snapshot(e.object_ptr,&e.object);
    s_boss_diag.focus_events[s_boss_diag.focus_write%RDB_BOSS_FOCUS_CAP]=e;
    s_boss_diag.focus_write++; s_boss_diag.focus_total++;
    if (s_boss_diag.focus_count<RDB_BOSS_FOCUS_CAP) s_boss_diag.focus_count++;
    else s_boss_diag.focus_overwritten++;
    if (preserve) {
        if (s_boss_diag.focus_first_count<RDB_BOSS_FOCUS_FIRST_CAP)
            s_boss_diag.focus_first[s_boss_diag.focus_first_count++]=e;
        else s_boss_diag.focus_first_overflow++;
    }
}

static int r2f_once(uint32_t pc,uint32_t frame,uint32_t epoch)
{
    for (unsigned i=0;i<32;i++)
        if (s_boss_diag.focus_probe_pc[i]==pc &&
            s_boss_diag.focus_probe_frame[i]==frame &&
            s_boss_diag.focus_probe_epoch[i]==epoch) return 0;
    unsigned n=s_boss_diag.focus_probe_next++%32u;
    s_boss_diag.focus_probe_pc[n]=pc; s_boss_diag.focus_probe_frame[n]=frame;
    s_boss_diag.focus_probe_epoch[n]=epoch; return 1;
}

static int r2f_state_changed(const RdbBossFocusObject *a,const RdbBossFocusObject *b)
{
    return a->active!=b->active || a->type!=b->type || a->state!=b->state ||
        a->word08!=b->word08 || a->map!=b->map || a->cursor!=b->cursor ||
        a->anim2a!=b->anim2a ||
        a->callback!=b->callback || a->link!=b->link;
}

static int r2f_watch_field(uint8_t o)
{
    return o<=0x13 || (o>=0x18&&o<=0x1D) || (o>=0x20&&o<=0x25) ||
        (o>=0x28&&o<=0x35) || (o>=0x38&&o<=0x45) ||
        (o>=0x48&&o<=0x4B) || (o>=0x50&&o<=0x53);
}

static int r2f_keep_first(uint8_t o,uint32_t pc)
{
    if ((o==0x0Au||o==0x0Bu) && pc==0x02A414u) return 1;
    return (o==0x28u||o==0x29u) &&
        ((pc>=0x02A400u&&pc<=0x02A420u)||pc==0x02B306u||pc==0x02B62Au);
}

static void r2f_candidate(uint32_t raw)
{
    uint32_t p=rdb_boss_normalize_object(raw);
    if (!p || rdb_boss_read8(0xFF37A6u)!=1) return;
    if (s_boss_diag.focus_manager && s_boss_diag.focus_manager!=p) {
        r2f_emit(R2F_CANDIDATE,p,0,0,s_boss_diag.focus_manager,0xFFu,0);
        return;
    }
    s_boss_diag.focus_candidate=p;
    s_boss_diag.focus_candidate_bytes_valid=1;
    for (uint32_t i=0;i<sizeof(s_boss_diag.focus_candidate_bytes);i++)
        s_boss_diag.focus_candidate_bytes[i]=rdb_boss_read8(p+i);
    r2f_emit(R2F_CANDIDATE,p,p,0,p,0xFFu,1);
}

static void r2f_root_write(void)
{
    uint32_t raw=rdb_boss_read32(0xFF5EE6u);
    uint32_t p=rdb_boss_normalize_object(raw);
    if (s_boss_diag.focus_candidate && p==s_boss_diag.focus_candidate &&
        !s_boss_diag.focus_candidate_confirmed) {
        s_boss_diag.focus_manager=p; s_boss_diag.focus_candidate_confirmed=1;
        for (uint32_t i=0;i<sizeof(s_boss_diag.focus_candidate_bytes);i++)
            s_boss_diag.focus_candidate_bytes[i]=rdb_boss_read8(p+i);
        r2f_emit(R2F_ROOT_CONFIRM,p,0xFF5EE6u,raw,p,0xFFu,1);
    } else if (s_boss_diag.focus_manager && p!=s_boss_diag.focus_manager) {
        r2f_emit(R2F_ROOT_CHANGE,s_boss_diag.focus_manager,0xFF5EE6u,
                 s_boss_diag.focus_manager,raw,0xFFu,1);
    }
}

static void r2f_write(uint32_t addr,uint8_t value)
{
    uint32_t p=s_boss_diag.focus_manager
        ? s_boss_diag.focus_manager : s_boss_diag.focus_candidate;
    if (p && s_boss_diag.focus_candidate_bytes_valid &&
        addr>=p && addr<p+sizeof(s_boss_diag.focus_candidate_bytes)) {
        uint8_t off=(uint8_t)(addr-p);
        if (r2f_watch_field(off)) {
            uint8_t before=s_boss_diag.focus_candidate_bytes[off];
            s_boss_diag.focus_candidate_bytes[off]=value;
            int keep=r2f_keep_first(off,g_rdb_boss_diag_pc);
            if (before!=value || keep) {
                uint8_t k=(off==0x0A||off==0x0B) &&
                    g_rdb_boss_diag_pc==0x036990u ? R2F_MAP_WRITE:R2F_FIELD_WRITE;
                r2f_emit(k,p,addr,before,value,off,keep);
            }
        }
    }
    if (s_boss_diag.focus_render_active && addr>=0xFFF500u && addr<0xFFFA00u) {
        RdbBossFocusEvent e;
        memset(&e,0,sizeof(e));
        e.seq=++s_boss_diag.seq; e.frame=cmd_server_current_frame();
        r2f_frame(e.frame); e.epoch=s_boss_diag.timeline_epoch;
        e.pc=g_rdb_boss_diag_pc&0xFFFFFFu; e.func=g_rdb_current_func&0xFFFFFFu;
        e.raw_manager=rdb_boss_read32(0xFF5EE6u); e.manager=s_boss_diag.focus_manager;
        e.object_ptr=s_boss_diag.focus_render_manager; e.addr=addr;
        e.before=0xFFFFFFFFu; e.after=value; e.value=value; e.field=0xFFu;
        e.stage=rdb_boss_read8(0xFF37A6u); e.kind=R2F_STAGE_WRITE;
        for(unsigned i=0;i<8;i++){e.d[i]=g_cpu.D[i];e.a[i]=g_cpu.A[i];}
        e.sr=g_cpu.SR; r2f_snapshot(e.object_ptr,&e.object);
        s_boss_diag.focus_events[s_boss_diag.focus_write%RDB_BOSS_FOCUS_CAP]=e;
        s_boss_diag.focus_write++; s_boss_diag.focus_total++;
        s_boss_diag.focus_stage_write_total++;
        if(s_boss_diag.focus_count<RDB_BOSS_FOCUS_CAP)s_boss_diag.focus_count++;
        else s_boss_diag.focus_overwritten++;
        if(s_boss_diag.focus_stage_count<RDB_BOSS_FOCUS_STAGE_CAP)
            s_boss_diag.focus_stage_events[s_boss_diag.focus_stage_count++]=e;
        else s_boss_diag.focus_stage_write_overflow++;
    }
}

static int r2f_anim_pc(uint32_t pc)
{
    switch(pc) {
    case 0x036794u: case 0x03679Au: case 0x03679Eu: case 0x0367A2u:
    case 0x0367A6u: case 0x0367DEu: case 0x036948u: case 0x036952u:
    case 0x03695Cu: case 0x03696Au: case 0x036982u: case 0x036988u:
    case 0x03698Cu: case 0x036990u: case 0x036994u: case 0x036716u:
    case 0x03671Au: return 1;
    default:return 0;
    }
}

static int r2f_pool_dispatch_pc(uint32_t pc)
{
    return pc==0x0366BCu||pc==0x0366C2u||pc==0x0366C6u||
           pc==0x0366CCu||pc==0x0366D0u||pc==0x0366F0u||
           pc==0x0366F4u||pc==0x0366FAu||pc==0x0366FEu;
}

static void r2f_probe(uint32_t pc)
{
    if(!g_rdb_boss_diag_enabled)return;
    uint32_t frame=cmd_server_current_frame(); r2f_frame(frame);
    if(pc==0x02A3CCu && rdb_boss_read8(0xFF37A6u)==1)
        r2f_emit(R2F_ALLOC_RESULT,0,0,0,g_cpu.D[0],0xFFu,1);
    if(pc==0x02A3CEu){r2f_candidate(g_cpu.A[6]);return;}

    uint32_t root=rdb_boss_normalize_object(rdb_boss_read32(0xFF5EE6u));
    if(!s_boss_diag.focus_manager && s_boss_diag.focus_candidate &&
       root==s_boss_diag.focus_candidate) r2f_root_write();
    uint32_t p=s_boss_diag.focus_manager?s_boss_diag.focus_manager:s_boss_diag.focus_candidate;
    if(!p)return;
    uint32_t object_reg = pc==0x0366BCu ? g_cpu.D[0] : g_cpu.A[0];
    uint32_t a0=rdb_boss_normalize_object(object_reg);
    int match=a0==p;

    if(pc==0x02B290u||pc==0x02B51Cu||pc==0x02B624u) {
        if(r2f_once(pc,frame,s_boss_diag.timeline_epoch))
            r2f_emit(R2F_MANAGER_HANDLER,p,pc,rdb_boss_read16(p+4),
                     rdb_boss_read16(p+0x0A),4,1);
        return;
    }

    if(r2f_pool_dispatch_pc(pc)) {
        s_boss_diag.focus_anim_probe_total++;
        if(match) {
            s_boss_diag.focus_anim_manager_matches++;
            s_boss_diag.focus_anim_pool_manager_matches++;
            if(r2f_once(pc,frame,s_boss_diag.timeline_epoch)) {
                uint32_t addr=(pc==0x0366CCu||pc==0x0366FAu)
                    ? (g_cpu.A[6]+(uint32_t)(int32_t)(int16_t)(g_cpu.D[0]&0xFFFFu))&0xFFFFFFu
                    : (pc==0x0366C2u||pc==0x0366F0u) ? p+2u
                    : pc==0x0366BCu ? object_reg : pc;
                uint32_t value=(pc==0x0366D0u||pc==0x0366FEu)?g_cpu.A[6]:
                    (pc==0x0366C2u||pc==0x0366F0u)?rdb_boss_read16(p+2u):g_cpu.D[0];
                r2f_emit(R2F_POOL_DISPATCH,p,addr,g_cpu.D[0],value,0x02u,0);
            }
        }
        return;
    }

    if(pc==0x02B104u && !match) {
        r2f_emit(R2F_MANAGER_TRANSITION,p,pc,p,g_cpu.A[0],0xFFu,1);
        return;
    }
    if(pc==0x02B104u && match) {
        RdbBossFocusObject now; r2f_snapshot(p,&now);
        int changed=!s_boss_diag.focus_last_valid ||
            r2f_state_changed(&now,&s_boss_diag.focus_last_object);
        int sample=!s_boss_diag.focus_last_valid ||
            s_boss_diag.focus_last_epoch!=s_boss_diag.timeline_epoch ||
            frame-s_boss_diag.focus_last_sample_frame>=16u;
        if(changed) {
            r2f_emit(R2F_MANAGER_TRANSITION,p,pc,
                s_boss_diag.focus_last_valid?s_boss_diag.focus_last_object.state:0xFFFFFFFFu,
                now.state,4,1);
            s_boss_diag.focus_last_object=now;s_boss_diag.focus_last_valid=1;
        } else if(sample) r2f_emit(R2F_MANAGER_SAMPLE,p,pc,0,0,0xFFu,0);
        if(sample){s_boss_diag.focus_last_sample_frame=frame;
            s_boss_diag.focus_last_epoch=s_boss_diag.timeline_epoch;}
    }

    if(r2f_anim_pc(pc)) {
        s_boss_diag.focus_anim_probe_total++;
        if(match) {
            s_boss_diag.focus_anim_manager_matches++;
            if(pc==0x0366BCu||pc==0x0366D0u||pc==0x0366FAu||pc==0x0366FEu)
                s_boss_diag.focus_anim_pool_manager_matches++;
            if(r2f_once(pc,frame,s_boss_diag.timeline_epoch)) {
                uint8_t k=pc==0x036988u?R2F_MAP_SOURCE:
                          pc==0x036990u?R2F_MAP_WRITE:R2F_ANIMATION;
                uint32_t addr=pc==0x036988u?
                    (g_cpu.A[1]+(uint32_t)(int32_t)(int16_t)(g_cpu.D[0]&0xFFFFu))&0xFFFFFFu:
                    pc==0x036990u?p+0x0Au:pc==0x036994u?p+0x28u:pc;
                uint32_t before=pc==0x036990u?rdb_boss_read16(p+0x0Au):
                    pc==0x036994u?rdb_boss_read16(p+0x28u):g_cpu.D[0];
                uint32_t after=pc==0x036990u?(g_cpu.D[0]&0xFFFFu):
                    pc==0x036994u?(uint16_t)(before+1u):
                    pc==0x03698Cu?(g_cpu.D[0]&0xFFFFu):
                    pc==0x036716u?rdb_boss_read32(p+0x48u):
                    pc==0x03671Au?g_cpu.A[6]:g_cpu.D[0];
                if(pc==0x036988u) {
                    s_boss_diag.focus_map_source_address=addr;
                    s_boss_diag.focus_map_source_index=g_cpu.D[0]&0xFFFFu;
                    s_boss_diag.focus_map_source_valid=1;
                }
                if(pc==0x03698Cu && s_boss_diag.focus_map_source_valid) {
                    addr=s_boss_diag.focus_map_source_address;
                    before=s_boss_diag.focus_map_source_index;
                    k=R2F_MAP_VALUE;
                    s_boss_diag.focus_map_source_valid=0;
                }
                if(pc==0x036716u) {addr=p+0x48u;k=R2F_ANIMATION;}
                r2f_emit(k,p,addr,before,after,
                    pc==0x036990u?0x0Au:pc==0x036994u?0x28u:0xFFu,
                    pc==0x036990u||pc==0x036994u||pc==0x03698Cu||pc==0x036716u);
            }
        }
        return;
    }

    if(pc==0x0014CAu && match) {
        s_boss_diag.focus_render_active=1;s_boss_diag.focus_render_manager=p;
        s_boss_diag.focus_render_frame=frame;s_boss_diag.focus_render_epoch=s_boss_diag.timeline_epoch;
        r2f_emit(R2F_RENDER_ENTRY,p,pc,0,rdb_boss_read16(p),0,1);
    } else if(pc==0x0014E2u && s_boss_diag.focus_render_active) {
        r2f_emit(R2F_RENDER_HIDE,s_boss_diag.focus_render_manager,pc,g_cpu.D[2],
                 g_cpu.D[2]&0x0880u,8,1);
    } else if(pc==0x0014E8u && s_boss_diag.focus_render_active) {
        uint16_t m=rdb_boss_read16(s_boss_diag.focus_render_manager+0xAu);
        r2f_emit(R2F_RENDER_MAP,s_boss_diag.focus_render_manager,pc,m,m,0xAu,1);
    } else if(pc==0x0014FAu && s_boss_diag.focus_render_active) {
        uint32_t a=(g_cpu.A[5]+(uint32_t)(int32_t)(int16_t)(g_cpu.D[0]&0xFFFFu))&0xFFFFFFu;
        r2f_emit(R2F_RENDER_DESC,s_boss_diag.focus_render_manager,a,
                 g_cpu.D[0]&0xFFFFu,g_cpu.D[0]&0xFFFFu,0xFFu,1);
    } else if(pc==0x0014FEu && s_boss_diag.focus_render_active) {
        r2f_emit(R2F_RENDER_DESC,s_boss_diag.focus_render_manager,g_cpu.A[3],
                 g_cpu.D[0],g_cpu.D[0],0xFFu,1);
    } else if((pc==0x0017A4u||pc==0x0019D4u)&&s_boss_diag.focus_render_active) {
        r2f_emit(R2F_CULL,s_boss_diag.focus_render_manager,pc,g_cpu.D[2],g_cpu.D[2],0xFFu,0);
    } else if(pc==0x001552u&&s_boss_diag.focus_render_active) {
        r2f_emit(R2F_SPRITE_EMIT,s_boss_diag.focus_render_manager,pc,g_cpu.D[6],0,0xFFu,0);
    } else if(pc==0x0014C8u) {
        s_boss_diag.focus_render_active=0;s_boss_diag.focus_render_manager=0;
    }
}

static void r2f_sat(const RdbBossSatEvent *e)
{
    if(!e||!e->manager||e->stage!=1)return;
    int same=s_boss_diag.focus_sat_signature_valid &&
        s_boss_diag.focus_sat_manager==e->manager &&
        s_boss_diag.focus_sat_active==e->object.active &&
        s_boss_diag.focus_sat_state==e->object.state &&
        s_boss_diag.focus_sat_map==e->object.map &&
        s_boss_diag.focus_sat_cursor==e->object.cursor;
    if(same)return;
    s_boss_diag.focus_sat_signature_valid=1;s_boss_diag.focus_sat_manager=e->manager;
    s_boss_diag.focus_sat_active=e->object.active;s_boss_diag.focus_sat_state=e->object.state;
    s_boss_diag.focus_sat_map=e->object.map;s_boss_diag.focus_sat_cursor=e->object.cursor;
    if(s_boss_diag.focus_sat_count<RDB_BOSS_FOCUS_SAT_CAP)
        s_boss_diag.focus_sat[s_boss_diag.focus_sat_count++]=*e;
    else s_boss_diag.focus_sat_overflow++;
}

static void r2f_write_json(FILE *f,const char *label,const RdbBossFocusEvent *e)
{
    fprintf(f,"{\"kind\":\"%s\",\"event\":\"%s\",\"seq\":%llu,\"frame\":%u,\"epoch\":%u,"
      "\"pc\":\"%06X\",\"func\":\"%06X\",\"stage\":%u,\"manager_raw\":\"%08X\","
      "\"manager\":\"%06X\",\"object_ptr\":\"%06X\",\"addr\":\"%06X\","
      "\"field_offset\":\"%02X\",\"before\":\"%08X\",\"after\":\"%08X\",\"value\":\"%02X\","
      "\"object\":{\"active\":\"%04X\",\"type\":\"%04X\",\"state\":\"%04X\",\"word08\":\"%04X\","
      "\"map\":\"%04X\",\"x\":\"%04X\",\"y\":\"%04X\",\"vx\":\"%04X\",\"vy\":\"%04X\","
      "\"cursor\":\"%04X\",\"anim2a\":\"%04X\",\"timer2c\":\"%04X\",\"word2e\":\"%04X\","
      "\"word30\":\"%04X\",\"word32\":\"%04X\",\"word34\":\"%04X\",\"word38\":\"%04X\","
      "\"word3a\":\"%04X\",\"word3c\":\"%04X\",\"word3e\":\"%04X\",\"word40\":\"%04X\","
      "\"word42\":\"%04X\",\"word44\":\"%04X\",\"callback\":\"%08X\",\"link\":\"%08X\"},"
      "\"sr\":\"%04X\",\"d\":[",
      label,r2f_name(e->kind),(unsigned long long)e->seq,e->frame,e->epoch,e->pc,e->func,
      e->stage,e->raw_manager,e->manager,e->object_ptr,e->addr,e->field,e->before,e->after,e->value,
      e->object.active,e->object.type,e->object.state,e->object.word08,e->object.map,e->object.x,
      e->object.y,e->object.vx,e->object.vy,e->object.cursor,e->object.anim2a,e->object.timer2c,
      e->object.word2e,e->object.word30,e->object.word32,e->object.word34,e->object.word38,
      e->object.word3a,e->object.word3c,e->object.word3e,e->object.word40,e->object.word42,
      e->object.word44,e->object.callback,e->object.link,e->sr);
    for(unsigned i=0;i<8;i++)fprintf(f,"%s\"%08X\"",i?",":"",e->d[i]);
    fprintf(f,"],\"a\":[");
    for(unsigned i=0;i<8;i++)fprintf(f,"%s\"%08X\"",i?",":"",e->a[i]);
    fprintf(f,"]}\n");
}
