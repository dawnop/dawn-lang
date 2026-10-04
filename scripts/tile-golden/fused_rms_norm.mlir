cuda_tile.module @m {
  entry @fused_rms_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_num_tile_blocks : tile<i32>
    %4 = constant <i32: 256> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<256xf64>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%9] token=%13 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<256xf64>, token
    %19 = addf %12, %17 rounding<nearest_even> : tile<256xf64>
    %20 = mulf %19, %19 rounding<nearest_even> : tile<256xf64>
    %21 = reduce %20 dim=0 identities=[0.0 : f64] : tile<256xf64> -> tile<f64> (%22: tile<f64>, %23: tile<f64>) {
      %24 = addf %22, %23 rounding<nearest_even> : tile<f64>
      yield %24 : tile<f64>
    }
    %25 = constant <f64: 256.0> : tile<f64>
    %26 = divf %21, %25 rounding<nearest_even> : tile<f64>
    %27 = constant <f64: 1.0E-5> : tile<f64>
    %28 = addf %26, %27 rounding<nearest_even> : tile<f64>
    %29 = sqrt %28 rounding<nearest_even> : tile<f64>
    %30 = reshape %29 : tile<f64> -> tile<1xf64>
    %31 = broadcast %30 : tile<1xf64> -> tile<256xf64>
    %32 = divf %19, %31 rounding<nearest_even> : tile<256xf64>
    %33 = constant <i32: 0> : tile<i32>
    %34 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %35 = make_tensor_view %34, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %36 = make_partition_view %35 : partition_view<tile=(256), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %37, %38 = load_view_tko weak %36[%33] token=%18 : partition_view<tile=(256), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<256xf64>, token
    %39 = mulf %32, %37 rounding<nearest_even> : tile<256xf64>
    %40 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %41 = make_tensor_view %40, shape = [%5], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %42 = make_partition_view %41 : partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %43 = store_view_tko weak %39, %42[%9] token=%38 : tile<256xf64>, partition_view<tile=(256), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
