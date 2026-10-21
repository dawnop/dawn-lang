cuda_tile.module @m {
  entry @view_max_pool(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 0> : tile<i32>
    %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %9 = offset %8, %7 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %11 = make_partition_view %10 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %12, %13 = load_view_tko weak %11[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %14 = constant <f64: -Infinity> : tile<16x16xf64>
    %15 = maxf %14, %12 : tile<16x16xf64>
    %16 = constant <i32: 1> : tile<i32>
    %17 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %18 = offset %17, %16 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %19 = make_tensor_view %18, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %20 = make_partition_view %19 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %21, %22 = load_view_tko weak %20[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %23 = maxf %15, %21 : tile<16x16xf64>
    %24 = constant <i32: 20> : tile<i32>
    %25 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %26 = offset %25, %24 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %27 = make_tensor_view %26, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %28 = make_partition_view %27 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %29, %30 = load_view_tko weak %28[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %31 = maxf %23, %29 : tile<16x16xf64>
    %32 = constant <i32: 21> : tile<i32>
    %33 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %34 = offset %33, %32 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %35 = make_tensor_view %34, shape = [18, 10], strides = [40, 2] : tensor_view<18x10xf64, strides=[40, 2]>
    %36 = make_partition_view %35 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>
    %37, %38 = load_view_tko weak %36[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = neg_inf, tensor_view<18x10xf64, strides=[40, 2]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %39 = maxf %31, %37 : tile<16x16xf64>
    %40 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %41 = make_tensor_view %40, shape = [18, 10], strides = [10, 1] : tensor_view<18x10xf64, strides=[10, 1]>
    %42 = make_partition_view %41 : partition_view<tile=(16x16), padding_value = zero, tensor_view<18x10xf64, strides=[10, 1]>, dim_map=[0, 1]>
    %43, %44, %45 = get_tile_block_id : tile<i32>
    %46, %47, %48 = get_tile_block_id : tile<i32>
    %49 = store_view_tko weak %39, %42[%43, %47] token=%0 : tile<16x16xf64>, partition_view<tile=(16x16), padding_value = zero, tensor_view<18x10xf64, strides=[10, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
