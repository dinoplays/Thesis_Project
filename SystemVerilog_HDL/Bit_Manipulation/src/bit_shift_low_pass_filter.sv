module bit_shift_low_pass_filter #(
    parameter int unsigned IMAGE_DIM    = 128,
    parameter int unsigned IMAGE_DIM_BS = 7
)(
    input  wire         clk,
    input  wire         pixel_valid_in,
    input  wire         soc_in,
    input  wire         eoc_in,
    input  wire         solf_in,
    input  wire         eolf_in,
    input  wire  [7:0]  pixel_in,
    output logic        pixel_valid_out,
    output logic        soc_out,
    output logic        eoc_out,
    output logic        solf_out,
    output logic        eolf_out,
    output logic [14:0] pixel_out
);

    // -------------------------------------------------------------------------
    // 7x7 low-pass kernel
    // Sum = 128, so output remains unsigned Q8.7
    // -------------------------------------------------------------------------
    localparam logic [1:0] kernel_7 [0:48] = '{
        0, 0, 1, 1, 1, 0, 0,
        0, 1, 2, 2, 2, 1, 0,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        1, 2, 2, 2, 2, 2, 1,
        0, 1, 2, 2, 2, 1, 0,
        0, 0, 1, 1, 1, 0, 0
    };

    localparam int unsigned BUFFER_LAST     = (6 << IMAGE_DIM_BS) + 6;
    localparam int unsigned LAG_BUFFER_MAX  = BUFFER_LAST;
    localparam int unsigned LAG_BUFFER_SIZE = $clog2(LAG_BUFFER_MAX + 1);

    // -------------------------------------------------------------------------
    // LF flags
    // -------------------------------------------------------------------------
    logic next_soc_is_solf = 1'b0;
    logic next_eoc_is_eolf = 1'b0;

    // -------------------------------------------------------------------------
    // Pixel buffer
    // Index 0 = oldest pixel, BUFFER_LAST = newest pixel
    // -------------------------------------------------------------------------
    logic [7:0] pixel_buffer [0:BUFFER_LAST];

    // -------------------------------------------------------------------------
    // Input counters and lag flags
    // -------------------------------------------------------------------------
    logic [IMAGE_DIM_BS-1:0] row_in_count    = '0;
    logic [IMAGE_DIM_BS-1:0] column_in_count = '0;

    // These counters intentionally keep the SAME semantics as the working
    // non-pipelined version: they represent the stage-0 output position used
    // for blur/raw selection before the counter update in that same cycle.
    logic [IMAGE_DIM_BS-1:0] row_out_count    = '0;
    logic [IMAGE_DIM_BS-1:0] column_out_count = '0;

    logic [LAG_BUFFER_SIZE-2:0] start_lag_buffer_count = '0;
    logic [LAG_BUFFER_SIZE-1:0] end_lag_buffer_count   = '0;

    logic soc_lag_flag  = 1'b0;
    logic eoc_lag_flag  = 1'b0;
    logic soc_out_pulse = 1'b0;
    logic eoc_out_pulse = 1'b0;

    // -------------------------------------------------------------------------
    // Stage-0 control signals
    // These match the working non-pipelined logic exactly.
    // -------------------------------------------------------------------------
    logic output_valid_now;
    logic soc_now;
    logic eoc_now;
    logic solf_now;
    logic eolf_now;
    logic output_step_now;
    logic is_convolved_now;

    assign output_valid_now =
        ((soc_lag_flag && pixel_valid_in) ||
         (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)));

    assign soc_now =
        ((soc_lag_flag && pixel_valid_in) && soc_out_pulse);

    assign eoc_now =
        ((eoc_lag_flag) &&
         (eoc_out_pulse) &&
         ((((column_in_count != '0) && pixel_valid_in) || (column_in_count == '0))));

    assign solf_now = (next_soc_is_solf && soc_now);
    assign eolf_now = (next_eoc_is_eolf && eoc_now);

    assign output_step_now =
        ((soc_lag_flag && pixel_valid_in && (!soc_out_pulse)) ||
         (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)));

    // -------------------------------------------------------------------------
    // EXACT same 7x7 edge selection logic as the working non-pipelined code.
    // Do NOT "predict" the next coordinate here.
    // -------------------------------------------------------------------------
    assign is_convolved_now =
        !(
            (row_out_count < 3) ||
            (row_out_count >= IMAGE_DIM - 3) ||
            ((row_out_count == IMAGE_DIM - 4) && (column_out_count == IMAGE_DIM - 1)) ||
            (column_out_count >= IMAGE_DIM - 5) ||
            (column_out_count == '0)
         );

    // -------------------------------------------------------------------------
    // Stage 0 registered taps
    // -------------------------------------------------------------------------
    logic [14:0] tap_s0 [0:48];
    logic [14:0] raw_s0 = 15'd0;

    logic        valid_s0 = 1'b0;
    logic        soc_s0   = 1'b0;
    logic        eoc_s0   = 1'b0;
    logic        solf_s0  = 1'b0;
    logic        eolf_s0  = 1'b0;
    logic        conv_s0  = 1'b0;

    // -------------------------------------------------------------------------
    // Reduction tree
    // 49 -> 25 -> 13 -> 7 -> 4 -> 2
    // Final add/select is done directly from stage 5 so control and pixel stay
    // aligned.
    // -------------------------------------------------------------------------
    logic [15:0] sum_s1 [0:24];
    logic [16:0] sum_s2 [0:12];
    logic [17:0] sum_s3 [0:6];
    logic [18:0] sum_s4 [0:3];
    logic [19:0] sum_s5 [0:1];

    logic [14:0] raw_s1 = 15'd0;
    logic [14:0] raw_s2 = 15'd0;
    logic [14:0] raw_s3 = 15'd0;
    logic [14:0] raw_s4 = 15'd0;
    logic [14:0] raw_s5 = 15'd0;

    logic        valid_s1 = 1'b0;
    logic        valid_s2 = 1'b0;
    logic        valid_s3 = 1'b0;
    logic        valid_s4 = 1'b0;
    logic        valid_s5 = 1'b0;

    logic        soc_s1 = 1'b0;
    logic        soc_s2 = 1'b0;
    logic        soc_s3 = 1'b0;
    logic        soc_s4 = 1'b0;
    logic        soc_s5 = 1'b0;

    logic        eoc_s1 = 1'b0;
    logic        eoc_s2 = 1'b0;
    logic        eoc_s3 = 1'b0;
    logic        eoc_s4 = 1'b0;
    logic        eoc_s5 = 1'b0;

    logic        solf_s1 = 1'b0;
    logic        solf_s2 = 1'b0;
    logic        solf_s3 = 1'b0;
    logic        solf_s4 = 1'b0;
    logic        solf_s5 = 1'b0;

    logic        eolf_s1 = 1'b0;
    logic        eolf_s2 = 1'b0;
    logic        eolf_s3 = 1'b0;
    logic        eolf_s4 = 1'b0;
    logic        eolf_s5 = 1'b0;

    logic        conv_s1 = 1'b0;
    logic        conv_s2 = 1'b0;
    logic        conv_s3 = 1'b0;
    logic        conv_s4 = 1'b0;
    logic        conv_s5 = 1'b0;

    integer idx;
    integer r_idx;
    integer c_idx;
    integer tap_idx;
    integer buf_idx;

    // -------------------------------------------------------------------------
    // Image buffer / lag logic
    // Keep timing decisions aligned to STAGE-0 launch timing.
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Image_Buffer
        if (soc_in) begin
            row_in_count           <= '0;
            column_in_count        <= '0;
            soc_lag_flag           <= 1'b0;
            start_lag_buffer_count <= {{(LAG_BUFFER_SIZE-2){1'b0}}, 1'b1};
        end

        if (eoc_in) begin
            eoc_lag_flag    <= 1'b1;
            row_in_count    <= '0;
            column_in_count <= '0;
        end

        // Match original behavior to the logical start of output stream,
        // not the delayed external pulse.
        if (soc_now) begin
            end_lag_buffer_count <= '0;
        end

        // Clear state once the logical end-of-light-field output is launched
        // into the pipeline.
        if (eolf_now) begin
            row_in_count           <= '0;
            column_in_count        <= '0;
            start_lag_buffer_count <= '0;
            end_lag_buffer_count   <= '0;
            soc_lag_flag           <= 1'b0;
            eoc_lag_flag           <= 1'b0;
            soc_out_pulse          <= 1'b0;
            eoc_out_pulse          <= 1'b0;
        end

        if (eoc_lag_flag && (((row_in_count == '0) && (column_in_count == '0)) || pixel_valid_in)) begin
            end_lag_buffer_count <= end_lag_buffer_count + {{(LAG_BUFFER_SIZE-1){1'b0}}, 1'b1};

            if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 2) begin
                eoc_out_pulse <= 1'b1;
            end

            if (end_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                eoc_lag_flag <= 1'b0;
            end
        end

        if (pixel_valid_in || (eoc_lag_flag && (row_in_count == '0) && (column_in_count == '0))) begin
            for (idx = 0; idx < BUFFER_LAST; idx = idx + 1) begin
                pixel_buffer[idx] <= pixel_buffer[idx + 1];
            end

            if (pixel_valid_in) begin
                pixel_buffer[BUFFER_LAST] <= pixel_in;

                if (!soc_lag_flag) begin
                    start_lag_buffer_count <= start_lag_buffer_count + {{(LAG_BUFFER_SIZE-2){1'b0}}, 1'b1};

                    if (start_lag_buffer_count == (3 << IMAGE_DIM_BS) + 3) begin
                        soc_lag_flag  <= 1'b1;
                        soc_out_pulse <= 1'b1;
                    end
                end

                if (column_in_count == IMAGE_DIM - 1) begin
                    column_in_count <= '0;
                    row_in_count    <= row_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
                end
                else begin
                    column_in_count <= column_in_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
                end
            end
        end

        if (soc_out_pulse && pixel_valid_in) begin
            soc_out_pulse <= 1'b0;
        end

        if (eoc_out_pulse && ((((column_in_count != '0) && pixel_valid_in) || (column_in_count == '0)))) begin
            eoc_out_pulse <= 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // Main pipeline
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Convolution_Pipeline
        // ---------------------------------------------------------------------
        // LF flags from input side
        // ---------------------------------------------------------------------
        if (solf_in) begin
            next_soc_is_solf <= 1'b1;
        end

        if (eolf_in) begin
            next_eoc_is_eolf <= 1'b1;
        end

        if (solf_now) begin
            next_soc_is_solf <= 1'b0;
        end

        if (eolf_now) begin
            next_eoc_is_eolf <= 1'b0;
        end

        // ---------------------------------------------------------------------
        // Stage 0: register control + weighted taps + raw center
        // ---------------------------------------------------------------------
        valid_s0 <= output_valid_now;
        soc_s0   <= soc_now;
        eoc_s0   <= eoc_now;
        solf_s0  <= solf_now;
        eolf_s0  <= eolf_now;
        conv_s0  <= is_convolved_now;

        raw_s0 <= {pixel_buffer[(3 << IMAGE_DIM_BS) + 3], 7'd0};

        for (r_idx = 0; r_idx < 7; r_idx = r_idx + 1) begin
            for (c_idx = 0; c_idx < 7; c_idx = c_idx + 1) begin
                tap_idx = (r_idx * 7) + c_idx;
                buf_idx = (r_idx << IMAGE_DIM_BS) + c_idx;

                case (kernel_7[tap_idx])
                    2'd0: tap_s0[tap_idx] <= {7'd0, pixel_buffer[buf_idx]};
                    2'd1: tap_s0[tap_idx] <= {6'd0, pixel_buffer[buf_idx], 1'b0};
                    2'd2: tap_s0[tap_idx] <= {5'd0, pixel_buffer[buf_idx], 2'b00};
                    default: tap_s0[tap_idx] <= 15'd0;
                endcase
            end
        end

        // ---------------------------------------------------------------------
        // Stage 1: 49 -> 25
        // ---------------------------------------------------------------------
        valid_s1 <= valid_s0;
        soc_s1   <= soc_s0;
        eoc_s1   <= eoc_s0;
        solf_s1  <= solf_s0;
        eolf_s1  <= eolf_s0;
        conv_s1  <= conv_s0;
        raw_s1   <= raw_s0;

        for (idx = 0; idx < 24; idx = idx + 1) begin
            sum_s1[idx] <= {1'b0, tap_s0[(idx << 1)]} + {1'b0, tap_s0[(idx << 1) + 1]};
        end
        sum_s1[24] <= {1'b0, tap_s0[48]};

        // ---------------------------------------------------------------------
        // Stage 2: 25 -> 13
        // ---------------------------------------------------------------------
        valid_s2 <= valid_s1;
        soc_s2   <= soc_s1;
        eoc_s2   <= eoc_s1;
        solf_s2  <= solf_s1;
        eolf_s2  <= eolf_s1;
        conv_s2  <= conv_s1;
        raw_s2   <= raw_s1;

        for (idx = 0; idx < 12; idx = idx + 1) begin
            sum_s2[idx] <= {1'b0, sum_s1[(idx << 1)]} + {1'b0, sum_s1[(idx << 1) + 1]};
        end
        sum_s2[12] <= {1'b0, sum_s1[24]};

        // ---------------------------------------------------------------------
        // Stage 3: 13 -> 7
        // ---------------------------------------------------------------------
        valid_s3 <= valid_s2;
        soc_s3   <= soc_s2;
        eoc_s3   <= eoc_s2;
        solf_s3  <= solf_s2;
        eolf_s3  <= eolf_s2;
        conv_s3  <= conv_s2;
        raw_s3   <= raw_s2;

        for (idx = 0; idx < 6; idx = idx + 1) begin
            sum_s3[idx] <= {1'b0, sum_s2[(idx << 1)]} + {1'b0, sum_s2[(idx << 1) + 1]};
        end
        sum_s3[6] <= {1'b0, sum_s2[12]};

        // ---------------------------------------------------------------------
        // Stage 4: 7 -> 4
        // ---------------------------------------------------------------------
        valid_s4 <= valid_s3;
        soc_s4   <= soc_s3;
        eoc_s4   <= eoc_s3;
        solf_s4  <= solf_s3;
        eolf_s4  <= eolf_s3;
        conv_s4  <= conv_s3;
        raw_s4   <= raw_s3;

        for (idx = 0; idx < 3; idx = idx + 1) begin
            sum_s4[idx] <= {1'b0, sum_s3[(idx << 1)]} + {1'b0, sum_s3[(idx << 1) + 1]};
        end
        sum_s4[3] <= {1'b0, sum_s3[6]};

        // ---------------------------------------------------------------------
        // Stage 5: 4 -> 2
        // ---------------------------------------------------------------------
        valid_s5 <= valid_s4;
        soc_s5   <= soc_s4;
        eoc_s5   <= eoc_s4;
        solf_s5  <= solf_s4;
        eolf_s5  <= eolf_s4;
        conv_s5  <= conv_s4;
        raw_s5   <= raw_s4;

        sum_s5[0] <= {1'b0, sum_s4[0]} + {1'b0, sum_s4[1]};
        sum_s5[1] <= {1'b0, sum_s4[2]} + {1'b0, sum_s4[3]};

        // ---------------------------------------------------------------------
        // Final add/select
        // IMPORTANT:
        // Use stage-5 data directly for both the output flags and the pixel
        // output so they remain aligned. This removes the stale-register
        // mismatch that was causing the broken output.
        // ---------------------------------------------------------------------
        pixel_valid_out <= valid_s5;
        soc_out         <= soc_s5;
        eoc_out         <= eoc_s5;
        solf_out        <= solf_s5;
        eolf_out        <= eolf_s5;

        if (conv_s5) begin
            pixel_out <= sum_s5[0] + sum_s5[1];
        end
        else begin
            pixel_out <= raw_s5;
        end

        // ---------------------------------------------------------------------
        // Stage-0 output coordinate tracking
        // This intentionally matches the working code:
        // - decide using current row_out_count / column_out_count
        // - then update the counters afterward in the same clock
        // ---------------------------------------------------------------------
        if (eoc_now) begin
            row_out_count    <= '0;
            column_out_count <= '0;
        end
        else if (output_step_now) begin
            if (column_out_count == IMAGE_DIM - 1) begin
                column_out_count <= '0;
                row_out_count    <= row_out_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
            end
            else begin
                column_out_count <= column_out_count + {{(IMAGE_DIM_BS-1){1'b0}}, 1'b1};
            end
        end
    end

endmodule