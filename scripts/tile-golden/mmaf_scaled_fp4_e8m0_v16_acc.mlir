cuda_tile.module @m {
  entry @mmaf_scaled_fp4_e8m0_v16_acc(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f8E8M0FNU>>, %arg3: tile<ptr<f8E8M0FNU>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<512xi32>, token
    %9 = pack %7 : tile<512xi32> -> tile<2048xi8>
    %10 = unpack %9 : tile<2048xi8> -> tile<4096xf4E2M1FN>
    %11 = reshape %10 : tile<4096xf4E2M1FN> -> tile<64x64xf4E2M1FN>
    %12 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %13 = make_tensor_view %12, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %14 = make_partition_view %13 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %15, %16 = load_view_tko weak %14[%4] token=%0 : partition_view<tile=(512), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<512xi32>, token
    %17 = pack %15 : tile<512xi32> -> tile<2048xi8>
    %18 = unpack %17 : tile<2048xi8> -> tile<4096xf4E2M1FN>
    %19 = reshape %18 : tile<4096xf4E2M1FN> -> tile<64x64xf4E2M1FN>
    %20 = constant <i32: 0> : tile<i32>
    %21 = reshape %20 : tile<i32> -> tile<1x1xi32>
    %22 = broadcast %21 : tile<1x1xi32> -> tile<64x64xi32>
    %23 = iota : tile<64xi32>
    %24 = reshape %23 : tile<64xi32> -> tile<64x1xi32>
    %25 = broadcast %24 : tile<64x1xi32> -> tile<64x64xi32>
    %26 = constant <i32: 64> : tile<64x64xi32>
    %27 = muli %25, %26 : tile<64x64xi32>
    %28 = addi %22, %27 : tile<64x64xi32>
    %29 = iota : tile<64xi32>
    %30 = reshape %29 : tile<64xi32> -> tile<1x64xi32>
    %31 = broadcast %30 : tile<1x64xi32> -> tile<64x64xi32>
    %32 = addi %28, %31 : tile<64x64xi32>
    %33 = constant <i32: 1> : tile<64x64xi32>
    %34 = addi %32, %33 : tile<64x64xi32>
    %35 = itof %34 signed rounding<nearest_even> : tile<64x64xi32> -> tile<64x64xf32>
    %36 = constant <i32: 2> : tile<64x64xi32>
    %37 = remi %32, %36 signed : tile<64x64xi32>
    %38 = constant <i32: 0> : tile<64x64xi32>
    %39 = cmpi equal %37, %38, signed : tile<64x64xi32> -> tile<64x64xi1>
    %40 = constant <f32: 0.0> : tile<64x64xf32>
    %41 = subf %40, %35 rounding<nearest_even> : tile<64x64xf32>
    %42 = select %39, %35, %41 : tile<64x64xi1>, tile<64x64xf32>
    %43 = assume div_by<16>, %arg2 : tile<ptr<f8E8M0FNU>>
    %44 = make_tensor_view %43, shape = [64, 4], strides = [4, 1] : tensor_view<64x4xf8E8M0FNU, strides=[4, 1]>
    %45 = make_partition_view %44 : partition_view<tile=(64x4), padding_value = zero, tensor_view<64x4xf8E8M0FNU, strides=[4, 1]>, dim_map=[0, 1]>
    %46, %47, %48 = get_tile_block_id : tile<i32>
    %49, %50 = load_view_tko weak %45[%4, %47] token=%0 : partition_view<tile=(64x4), padding_value = zero, tensor_view<64x4xf8E8M0FNU, strides=[4, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x4xf8E8M0FNU>, token
    %51 = assume div_by<16>, %arg3 : tile<ptr<f8E8M0FNU>>
    %52 = make_tensor_view %51, shape = [4, 64], strides = [64, 1] : tensor_view<4x64xf8E8M0FNU, strides=[64, 1]>
    %53 = make_partition_view %52 : partition_view<tile=(4x64), padding_value = zero, tensor_view<4x64xf8E8M0FNU, strides=[64, 1]>, dim_map=[0, 1]>
    %54, %55 = load_view_tko weak %53[%4, %47] token=%0 : partition_view<tile=(4x64), padding_value = zero, tensor_view<4x64xf8E8M0FNU, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<4x64xf8E8M0FNU>, token
    %56 = mmaf_scaled %11, %19, %42, %49, %54 : tile<64x64xf4E2M1FN>, tile<64x64xf4E2M1FN>, tile<64x64xf32>, tile<64x4xf8E8M0FNU>, tile<4x64xf8E8M0FNU>
    %57 = ftof %56 rounding<nearest_even> : tile<64x64xf32> -> tile<64x64xf64>
    %58 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %59 = make_tensor_view %58, shape = [64, 64], strides = [64, 1] : tensor_view<64x64xf64, strides=[64, 1]>
    %60 = make_partition_view %59 : partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>
    %61 = store_view_tko weak %57, %60[%4, %47] token=%0 : tile<64x64xf64>, partition_view<tile=(64x64), padding_value = zero, tensor_view<64x64xf64, strides=[64, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
