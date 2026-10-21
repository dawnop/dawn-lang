cuda_tile.module @m {
  entry @view_padding(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>, %arg3: tile<ptr<f32>>, %arg4: tile<ptr<f32>>, %arg5: tile<ptr<f32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_tile_block_id : tile<i32>
    %5 = assume div_by<16>, %arg0 : tile<ptr<f32>>
    %6 = offset %5, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %7 = make_tensor_view %6, shape = [100], strides = [1] : tensor_view<100xf32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(32), padding_value = zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %9 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %10 = offset %9, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %11 = make_tensor_view %10, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %12 = make_partition_view %11 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %13, %14 = load_view_tko weak %8[%2] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %15 = store_view_tko weak %13, %12[%2] token=%14 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %16 = make_partition_view %7 : partition_view<tile=(32), padding_value = neg_zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %17 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %18 = offset %17, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %19 = make_tensor_view %18, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %20 = make_partition_view %19 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %21, %22 = load_view_tko weak %16[%2] token=%15 : partition_view<tile=(32), padding_value = neg_zero, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %23 = store_view_tko weak %21, %20[%2] token=%22 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %24 = make_partition_view %7 : partition_view<tile=(32), padding_value = nan, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %25 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %26 = offset %25, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %27 = make_tensor_view %26, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %28 = make_partition_view %27 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %29, %30 = load_view_tko weak %24[%2] token=%23 : partition_view<tile=(32), padding_value = nan, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %31 = store_view_tko weak %29, %28[%2] token=%30 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %32 = make_partition_view %7 : partition_view<tile=(32), padding_value = pos_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %33 = assume div_by<16>, %arg4 : tile<ptr<f32>>
    %34 = offset %33, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %35 = make_tensor_view %34, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %36 = make_partition_view %35 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %37, %38 = load_view_tko weak %32[%2] token=%31 : partition_view<tile=(32), padding_value = pos_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %39 = store_view_tko weak %37, %36[%2] token=%38 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %40 = make_partition_view %7 : partition_view<tile=(32), padding_value = neg_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>
    %41 = assume div_by<16>, %arg5 : tile<ptr<f32>>
    %42 = offset %41, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %43 = make_tensor_view %42, shape = [128], strides = [1] : tensor_view<128xf32, strides=[1]>
    %44 = make_partition_view %43 : partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>
    %45, %46 = load_view_tko weak %40[%2] token=%39 : partition_view<tile=(32), padding_value = neg_inf, tensor_view<100xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf32>, token
    %47 = store_view_tko weak %45, %44[%2] token=%46 : tile<32xf32>, partition_view<tile=(32), tensor_view<128xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
