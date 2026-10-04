cuda_tile.module @m {
  entry @view_max_pool(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 0> : tile<i32>
    %8 = offset %arg0, %7 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %9 = make_tensor_view %8, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %10 = make_partition_view %9 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %11, %12 = load_view_tko weak %10[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %13 = constant <f64: -Infinity> : tile<16x16xf64>
    %14 = maxf %13, %11 : tile<16x16xf64>
    %15 = constant <i32: 1> : tile<i32>
    %16 = offset %arg0, %15 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %18 = make_partition_view %17 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %19, %20 = load_view_tko weak %18[%1, %5] token=%12 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %21 = maxf %14, %19 : tile<16x16xf64>
    %22 = constant <i32: 20> : tile<i32>
    %23 = offset %arg0, %22 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %24 = make_tensor_view %23, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %25 = make_partition_view %24 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %26, %27 = load_view_tko weak %25[%1, %5] token=%20 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %28 = maxf %21, %26 : tile<16x16xf64>
    %29 = constant <i32: 21> : tile<i32>
    %30 = offset %arg0, %29 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %31 = make_tensor_view %30, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %32 = make_partition_view %31 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %33, %34 = load_view_tko weak %32[%1, %5] token=%27 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %35 = maxf %28, %33 : tile<16x16xf64>
    %36 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %37 = make_tensor_view %36, shape = [18, 10], strides = [10, 1] : tensor_view<18x10xf64, strides=[10, 1]>
    %38 = make_partition_view %37 : partition_view<tile=(16x16), padding_value = zero, tensor_view<18x10xf64, strides=[10, 1]>, dim_map=[0, 1]>
    %39, %40, %41 = get_tile_block_id : tile<i32>
    %42, %43, %44 = get_tile_block_id : tile<i32>
    %45 = store_view_tko weak %35, %38[%39, %43] token=%34 : tile<16x16xf64>, partition_view<tile=(16x16), padding_value = zero, tensor_view<18x10xf64, strides=[10, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
