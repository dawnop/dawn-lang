cuda_tile.module @m {
  entry @gpt_gelu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [8192], strides = [1] : tensor_view<8192xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<8192xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<8192xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = mulf %7, %7 rounding<nearest_even> : tile<128xf64>
    %10 = mulf %7, %9 rounding<nearest_even> : tile<128xf64>
    %11 = constant <f64: 0.044715> : tile<128xf64>
    %12 = mulf %11, %10 rounding<nearest_even> : tile<128xf64>
    %13 = addf %7, %12 rounding<nearest_even> : tile<128xf64>
    %14 = constant <f64: 0.7978845608028654> : tile<128xf64>
    %15 = mulf %14, %13 rounding<nearest_even> : tile<128xf64>
    %16 = tanh %15 : tile<128xf64>
    %17 = constant <f64: 1.0> : tile<128xf64>
    %18 = addf %17, %16 rounding<nearest_even> : tile<128xf64>
    %19 = constant <f64: 0.5> : tile<128xf64>
    %20 = mulf %19, %7 rounding<nearest_even> : tile<128xf64>
    %21 = mulf %20, %18 rounding<nearest_even> : tile<128xf64>
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [8192], strides = [1] : tensor_view<8192xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(128), padding_value = zero, tensor_view<8192xf64, strides=[1]>, dim_map=[0]>
    %25 = store_view_tko weak %21, %24[%4] token=%8 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<8192xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
