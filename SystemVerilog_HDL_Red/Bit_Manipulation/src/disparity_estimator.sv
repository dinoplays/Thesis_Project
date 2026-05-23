module disparity_estimator #(
    parameter int unsigned IMAGE_DIM    = 128,
    parameter int unsigned IMAGE_DIM_BS = 7
)(
    input  wire                             clk,

    // Aligned derivative stream from confidence_computer.
    input  wire                             derivative_valid_in,
    input  wire signed [10:0]               angular_derivative_column_in [0:6],
    input  wire signed [10:0]               spatial_derivative_column_in [0:6],
    input  wire [IMAGE_DIM_BS-1:0]          derivative_row_idx_in,
    input  wire [IMAGE_DIM_BS-1:0]          derivative_column_idx_in,
    input  wire                             derivative_orientation_in,

    output logic                            disparity_valid_out,
    output logic signed [15:0]              disparity_pixel_out,
    output logic [IMAGE_DIM_BS-1:0]         disparity_row_idx_out,
    output logic [IMAGE_DIM_BS-1:0]         disparity_column_idx_out,
    output logic                            orientation_out
);

    localparam int unsigned DIVIDEND_W     = 33; // abs(sum_uv)[24:0] << 8
    localparam int unsigned DIVISOR_W      = 23; // sum_uu maximum fits in 23 bits for signed [10:0] Q8.2 derivatives
    localparam int unsigned QUOTIENT_W     = 33; // keep full quotient during division, then saturate to signed Q8.8
    localparam int unsigned DIV_ITERATIONS = DIVIDEND_W; // restoring division must process all dividend bits

    function automatic logic [24:0] abs25(
        input logic signed [24:0] x
    );
        begin
            if (x < 0) begin
                abs25 = $unsigned(-x);
            end
            else begin
                abs25 = $unsigned(x);
            end
        end
    endfunction

    function automatic logic signed [15:0] saturate_q8_8(
        input logic                  sign_bit,
        input logic [QUOTIENT_W-1:0] magnitude
    );
        logic signed [15:0] tmp16;
        begin
            if (sign_bit == 1'b0) begin
                if (magnitude > {{(QUOTIENT_W-15){1'b0}}, 15'h7FFF}) begin
                    saturate_q8_8 = 16'sh7FFF;
                end
                else begin
                    saturate_q8_8 = $signed(magnitude[15:0]);
                end
            end
            else begin
                if (magnitude >= {{(QUOTIENT_W-16){1'b0}}, 16'h8000}) begin
                    saturate_q8_8 = 16'sh8000;
                end
                else begin
                    tmp16 = $signed(magnitude[15:0]);
                    saturate_q8_8 = -tmp16;
                end
            end
        end
    endfunction

    function automatic logic signed [15:0] add_one_q8_8_sat(
        input logic signed [15:0] x
    );
        logic signed [16:0] tmp;
        begin
            tmp = $signed({x[15], x}) + 17'sd256;

            if (tmp > 17'sd32767) begin
                add_one_q8_8_sat = 16'sh7FFF;
            end
            else if (tmp < -17'sd32768) begin
                add_one_q8_8_sat = 16'sh8000;
            end
            else begin
                add_one_q8_8_sat = tmp[15:0];
            end
        end
    endfunction

    // -------------------------------------------------------------------------
    // Product stage
    // -------------------------------------------------------------------------
    logic signed [21:0] uv_0 = 0;
    logic signed [21:0] uv_1 = 0;
    logic signed [21:0] uv_2 = 0;
    logic signed [21:0] uv_3 = 0;
    logic signed [21:0] uv_4 = 0;
    logic signed [21:0] uv_5 = 0;
    logic signed [21:0] uv_6 = 0;

    logic signed [21:0] uu_0 = 0;
    logic signed [21:0] uu_1 = 0;
    logic signed [21:0] uu_2 = 0;
    logic signed [21:0] uu_3 = 0;
    logic signed [21:0] uu_4 = 0;
    logic signed [21:0] uu_5 = 0;
    logic signed [21:0] uu_6 = 0;

    logic                    prod_valid       = 1'b0;
    logic [IMAGE_DIM_BS-1:0] prod_row_idx     = '0;
    logic [IMAGE_DIM_BS-1:0] prod_column_idx  = '0;
    logic                    prod_orientation = 1'b0;

    always_ff @(posedge clk) begin : Product_Computations
        uv_0 <= angular_derivative_column_in[0] * spatial_derivative_column_in[0];
        uv_1 <= angular_derivative_column_in[1] * spatial_derivative_column_in[1];
        uv_2 <= angular_derivative_column_in[2] * spatial_derivative_column_in[2];
        uv_3 <= angular_derivative_column_in[3] * spatial_derivative_column_in[3];
        uv_4 <= angular_derivative_column_in[4] * spatial_derivative_column_in[4];
        uv_5 <= angular_derivative_column_in[5] * spatial_derivative_column_in[5];
        uv_6 <= angular_derivative_column_in[6] * spatial_derivative_column_in[6];

        uu_0 <= angular_derivative_column_in[0] * angular_derivative_column_in[0];
        uu_1 <= angular_derivative_column_in[1] * angular_derivative_column_in[1];
        uu_2 <= angular_derivative_column_in[2] * angular_derivative_column_in[2];
        uu_3 <= angular_derivative_column_in[3] * angular_derivative_column_in[3];
        uu_4 <= angular_derivative_column_in[4] * angular_derivative_column_in[4];
        uu_5 <= angular_derivative_column_in[5] * angular_derivative_column_in[5];
        uu_6 <= angular_derivative_column_in[6] * angular_derivative_column_in[6];

        prod_valid       <= derivative_valid_in;
        prod_row_idx     <= derivative_row_idx_in;
        prod_column_idx  <= derivative_column_idx_in;
        prod_orientation <= derivative_orientation_in;
    end

    // -------------------------------------------------------------------------
    // Pipelined adder tree
    // -------------------------------------------------------------------------
    logic signed [22:0] uv_s1_0 = 0;
    logic signed [22:0] uv_s1_1 = 0;
    logic signed [22:0] uv_s1_2 = 0;
    logic signed [22:0] uv_s1_3 = 0;

    logic signed [22:0] uu_s1_0 = 0;
    logic signed [22:0] uu_s1_1 = 0;
    logic signed [22:0] uu_s1_2 = 0;
    logic signed [22:0] uu_s1_3 = 0;

    logic                    sum1_valid       = 1'b0;
    logic [IMAGE_DIM_BS-1:0] sum1_row_idx     = '0;
    logic [IMAGE_DIM_BS-1:0] sum1_column_idx  = '0;
    logic                    sum1_orientation = 1'b0;

    always_ff @(posedge clk) begin : Sum_Tree_Stage1
        uv_s1_0 <= $signed(uv_0) + $signed(uv_1);
        uv_s1_1 <= $signed(uv_2) + $signed(uv_3);
        uv_s1_2 <= $signed(uv_4) + $signed(uv_5);
        uv_s1_3 <= $signed(uv_6);

        uu_s1_0 <= $signed(uu_0) + $signed(uu_1);
        uu_s1_1 <= $signed(uu_2) + $signed(uu_3);
        uu_s1_2 <= $signed(uu_4) + $signed(uu_5);
        uu_s1_3 <= $signed(uu_6);

        sum1_valid       <= prod_valid;
        sum1_row_idx     <= prod_row_idx;
        sum1_column_idx  <= prod_column_idx;
        sum1_orientation <= prod_orientation;
    end

    logic signed [23:0] uv_s2_0 = 0;
    logic signed [23:0] uv_s2_1 = 0;

    logic signed [23:0] uu_s2_0 = 0;
    logic signed [23:0] uu_s2_1 = 0;

    logic                    sum2_valid       = 1'b0;
    logic [IMAGE_DIM_BS-1:0] sum2_row_idx     = '0;
    logic [IMAGE_DIM_BS-1:0] sum2_column_idx  = '0;
    logic                    sum2_orientation = 1'b0;

    always_ff @(posedge clk) begin : Sum_Tree_Stage2
        uv_s2_0 <= $signed(uv_s1_0) + $signed(uv_s1_1);
        uv_s2_1 <= $signed(uv_s1_2) + $signed(uv_s1_3);

        uu_s2_0 <= $signed(uu_s1_0) + $signed(uu_s1_1);
        uu_s2_1 <= $signed(uu_s1_2) + $signed(uu_s1_3);

        sum2_valid       <= sum1_valid;
        sum2_row_idx     <= sum1_row_idx;
        sum2_column_idx  <= sum1_column_idx;
        sum2_orientation <= sum1_orientation;
    end

    logic signed [24:0] sum_uv = 0;
    logic signed [24:0] sum_uu = 0;

    logic                    sum_valid       = 1'b0;
    logic [IMAGE_DIM_BS-1:0] sum_row_idx     = '0;
    logic [IMAGE_DIM_BS-1:0] sum_column_idx  = '0;
    logic                    sum_orientation = 1'b0;

    always_ff @(posedge clk) begin : Sum_Tree_Stage3
        sum_uv <= $signed(uv_s2_0) + $signed(uv_s2_1);
        sum_uu <= $signed(uu_s2_0) + $signed(uu_s2_1);

        sum_valid       <= sum2_valid;
        sum_row_idx     <= sum2_row_idx;
        sum_column_idx  <= sum2_column_idx;
        sum_orientation <= sum2_orientation;
    end

    // -------------------------------------------------------------------------
    // Divider pipeline
    // -------------------------------------------------------------------------
    logic [DIVIDEND_W-1:0] dividend_pipe  [0:DIV_ITERATIONS];
    logic [DIVISOR_W-1:0]  divisor_pipe   [0:DIV_ITERATIONS];
    logic [DIVISOR_W:0]    remainder_pipe [0:DIV_ITERATIONS];
    logic [QUOTIENT_W-1:0] quotient_pipe  [0:DIV_ITERATIONS];

    logic                  valid_pipe     [0:DIV_ITERATIONS];
    logic                  sign_pipe      [0:DIV_ITERATIONS];
    logic                  div_zero_pipe  [0:DIV_ITERATIONS];

    logic [IMAGE_DIM_BS-1:0] row_idx_pipe     [0:DIV_ITERATIONS];
    logic [IMAGE_DIM_BS-1:0] column_idx_pipe  [0:DIV_ITERATIONS];
    logic                    orientation_pipe [0:DIV_ITERATIONS];

    always_ff @(posedge clk) begin : Divider_Load
        valid_pipe[0]       <= sum_valid;
        sign_pipe[0]        <= sum_uv[24];
        div_zero_pipe[0]    <= (sum_uu == 25'sd0);
        row_idx_pipe[0]     <= sum_row_idx;
        column_idx_pipe[0]  <= sum_column_idx;
        orientation_pipe[0] <= sum_orientation;

        if (sum_valid && (sum_uu != 25'sd0)) begin
            dividend_pipe[0]  <= {abs25(sum_uv), 8'd0};
            divisor_pipe[0]   <= sum_uu[DIVISOR_W-1:0];
            remainder_pipe[0] <= '0;
            quotient_pipe[0]  <= '0;
        end
        else begin
            dividend_pipe[0]  <= '0;
            divisor_pipe[0]   <= '0;
            remainder_pipe[0] <= '0;
            quotient_pipe[0]  <= '0;
        end
    end

    genvar s;
    generate
        for (s = 0; s < DIV_ITERATIONS; s = s + 1) begin : Divider_Pipeline
            always_ff @(posedge clk) begin
                valid_pipe[s+1]       <= valid_pipe[s];
                sign_pipe[s+1]        <= sign_pipe[s];
                div_zero_pipe[s+1]    <= div_zero_pipe[s];
                row_idx_pipe[s+1]     <= row_idx_pipe[s];
                column_idx_pipe[s+1]  <= column_idx_pipe[s];
                orientation_pipe[s+1] <= orientation_pipe[s];

                divisor_pipe[s+1] <= divisor_pipe[s];

                if (!valid_pipe[s] || div_zero_pipe[s]) begin
                    dividend_pipe[s+1]  <= '0;
                    remainder_pipe[s+1] <= '0;
                    quotient_pipe[s+1]  <= '0;
                end
                else begin
                    if ({remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]} >= {1'b0, divisor_pipe[s]}) begin
                        remainder_pipe[s+1] <= {remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]} - {1'b0, divisor_pipe[s]};
                        quotient_pipe[s+1]  <= {quotient_pipe[s][QUOTIENT_W-2:0], 1'b1};
                    end
                    else begin
                        remainder_pipe[s+1] <= {remainder_pipe[s][DIVISOR_W-1:0], dividend_pipe[s][DIVIDEND_W-1]};
                        quotient_pipe[s+1]  <= {quotient_pipe[s][QUOTIENT_W-2:0], 1'b0};
                    end

                    dividend_pipe[s+1] <= {dividend_pipe[s][DIVIDEND_W-2:0], 1'b0};
                end
            end
        end
    endgenerate

    // -------------------------------------------------------------------------
    // Output stage
    // -------------------------------------------------------------------------
    always_ff @(posedge clk) begin : Output_Stage
        disparity_valid_out      <= 1'b0;
        disparity_pixel_out      <= 16'sd0;
        disparity_row_idx_out    <= '0;
        disparity_column_idx_out <= '0;
        orientation_out          <= 1'b0;

        if (valid_pipe[DIV_ITERATIONS]) begin
            disparity_valid_out      <= 1'b1;
            disparity_row_idx_out    <= row_idx_pipe[DIV_ITERATIONS];
            disparity_column_idx_out <= column_idx_pipe[DIV_ITERATIONS];
            orientation_out          <= orientation_pipe[DIV_ITERATIONS];

            if (div_zero_pipe[DIV_ITERATIONS]) begin
                disparity_pixel_out <= 16'sd0;
            end
            else begin
                disparity_pixel_out <= add_one_q8_8_sat(
                    saturate_q8_8(
                        sign_pipe[DIV_ITERATIONS],
                        quotient_pipe[DIV_ITERATIONS]
                    )
                );
            end
        end
    end

endmodule