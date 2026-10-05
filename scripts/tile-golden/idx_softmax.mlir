cuda_tile.module @m {
  entry @idx_softmax(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 8> : tile<i32>
    %5 = constant <i32: 2> : tile<i32>
    %6 = divi %4, %5 signed : tile<i32>
    %7 = addi %1, %6 : tile<i32>
    %8 = remi %7, %4 signed : tile<i32>
    %9 = subi %4, %1 : tile<i32>
    %10 = constant <i32: 1> : tile<i32>
    %11 = subi %9, %10 : tile<i32>
    %12 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %13 = make_tensor_view %12, shape = [128, 64], strides = [64, 1] : tensor_view<128x64xf64, strides=[64, 1]>
    %14 = make_partition_view %13 : partition_view<tile=(16x64), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %15, %16, %17 = get_tile_block_id : tile<i32>
    %18, %19 = load_view_tko weak %14[%8, %16] token=%0 : partition_view<tile=(16x64), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x64xf64>, token
    %20, %21 = load_view_tko weak %14[%11, %16] token=%19 : partition_view<tile=(16x64), padding_value = zero, tensor_view<128x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x64xf64>, token
    %22 = addf %18, %20 rounding<nearest_even> : tile<16x64xf64>
    %23 = reduce %22 dim=1 identities=[-Infinity : f64] : tile<16x64xf64> -> tile<16xf64> (%24: tile<f64>, %25: tile<f64>) {
      %26 = maxf %24, %25 : tile<f64>
      yield %26 : tile<f64>
    }
    %27 = reshape %23 : tile<16xf64> -> tile<16x1xf64>
    %28 = broadcast %27 : tile<16x1xf64> -> tile<16x64xf64>
    %29 = subf %22, %28 rounding<nearest_even> : tile<16x64xf64>
    %30 = exp %29 : tile<16x64xf64>
    %31 = reduce %30 dim=1 identities=[0.0 : f64] : tile<16x64xf64> -> tile<16xf64> (%32: tile<f64>, %33: tile<f64>) {
      %34 = addf %32, %33 rounding<nearest_even> : tile<f64>
      yield %34 : tile<f64>
    }
    %35 = reshape %31 : tile<16xf64> -> tile<16x1xf64>
    %36 = broadcast %35 : tile<16x1xf64> -> tile<16x64xf64>
    %37 = divf %30, %36 rounding<nearest_even> : tile<16x64xf64>
    %38 = constant <f64: 2.0> : tile<16x64xf64>
    %39 = mulf %37, %38 rounding<nearest_even> : tile<16x64xf64>
    %40 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %41 = make_tensor_view %40, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %42 = make_partition_view %41 : partition_view<tile=(16x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %43, %44, %45 = get_tile_block_id : tile<i32>
    %46 = store_view_tko weak %39, %42[%43, %16] token=%21 : tile<16x64xf64>, partition_view<tile=(16x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
